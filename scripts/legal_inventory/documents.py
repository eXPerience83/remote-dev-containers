"""Source-locked legal document refresh, validation and human rendering."""
from __future__ import annotations
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from .discovery import parse_apt_packages
from .inventory import expected_source_documents, inventory_components, resolve_component_version
from .io import SCHEMA_VERSION, InventoryError, git_blob_sha1, load_json, write_json

def validate_sources(
    root: Path,
    inventory: dict[str, Any],
    env: dict[str, str],
    mise: dict[str, dict[str, Any]],
) -> None:
    """Verify source-locked legal documents against exact versions and blobs."""
    lock_path = root / "third_party/sources.lock.json"
    lock = load_json(lock_path)
    if lock.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError("unsupported third-party source lock schema")
    records = lock.get("documents")
    if not isinstance(records, list):
        raise InventoryError("source lock documents must be an array")
    expected = expected_source_documents(inventory, env, mise)
    expected_by_path = {document.path: document for document in expected}
    if len(expected_by_path) != len(expected):
        raise InventoryError("source document paths must be unique")
    actual_by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise InventoryError("source lock record must be an object")
        path = record.get("path")
        if not isinstance(path, str) or path in actual_by_path:
            raise InventoryError(f"invalid or duplicate source lock path: {path!r}")
        actual_by_path[path] = record
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    extra = sorted(set(actual_by_path) - set(expected_by_path))
    if missing or extra:
        raise InventoryError(f"source lock mismatch; missing={missing}, extra={extra}")
    for path, document in expected_by_path.items():
        record = actual_by_path[path]
        if record.get("component") != document.component_id:
            raise InventoryError(f"source lock component mismatch for {path}")
        if record.get("version") != document.version:
            raise InventoryError(f"source lock version is stale for {path}: {record.get('version')} != {document.version}")
        if record.get("url") != document.url:
            raise InventoryError(f"source lock URL is stale for {path}: {record.get('url')} != {document.url}")
        expected_blob = record.get("git_blob_sha1")
        if not isinstance(expected_blob, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_blob):
            raise InventoryError(f"invalid Git blob SHA-1 for {path}")
        file_path = root / path
        try:
            data = file_path.read_bytes()
        except FileNotFoundError as exc:
            raise InventoryError(f"source document is missing: {path}") from exc
        if not data:
            raise InventoryError(f"source document is empty: {path}")
        actual_blob = git_blob_sha1(data)
        if actual_blob != expected_blob:
            raise InventoryError(f"source document differs from reviewed lock: {path}")

def render_readme(root: Path, inventory: dict[str, Any], env: dict[str, str], mise: dict[str, dict[str, Any]]) -> str:
    """Render the human inventory from machine data and build recipes."""
    components = inventory_components(inventory)
    apt_packages = parse_apt_packages(root / "images/base/Dockerfile")
    lines = [
        "# Third-party software and notices",
        "",
        "Remote Dev project code is licensed under Apache-2.0. That project license does not replace, extend or relicense software supplied by Ubuntu, OpenAI, GitHub, Google, Astral or other upstream projects.",
        "",
        "This file is generated from `third_party/inventory.json` and the current build recipes. Edit the machine-readable inventory, then run `python3 scripts/legal-inventory.py render`. It is an attribution and maintenance record, not legal advice.",
        "",
        "## Inspecting notices",
        "",
        "In a built image, run:",
        "",
        "```text",
        "remote-dev-notices",
        "remote-dev-notices --versions",
        "remote-dev-notices --list",
        "remote-dev-notices --check",
        "```",
        "",
        "The canonical image path is `/usr/share/doc/remote-dev/third_party`.",
        "",
        "`BUILD-VERSIONS.env` records exact build values and locked runtime artifact URLs/checksums. `sources.lock.json` binds every repository-preserved upstream legal document to its exact version, URL and Git blob identity. Ubuntu package copyright files remain under `/usr/share/doc/<package>/copyright`. Generated SPDX SBOMs are reconciled against this inventory in CI; they supplement rather than replace required notices.",
        "",
        "Because the image aggregates software under many licenses, it deliberately does not set `org.opencontainers.image.licenses` to a project-only value. Project-owned code is identified separately by `io.github.experience83.remote-dev.project-license=Apache-2.0`.",
        "",
        "## Bundled component inventory",
        "",
        "| Component | Exact version source | Distribution and upstream | License / notice treatment | Image notice location | SBOM treatment |",
        "|---|---|---|---|---|---|",
    ]
    scope_suffix = {
        "base": "base image",
        "final": "final image only",
        "both": "base and final images",
        "project": "project files",
        "optional": "not redistributed",
    }
    for component in components:
        version = resolve_component_version(component, env, mise)
        source = component["version_source"]
        if source["kind"] == "env":
            version_text = f"`{source['key']}` = `{version}`"
        elif source["kind"] == "mise":
            version_text = f"`mise.lock` tool `{source['tool']}` = `{version}`"
        elif source["kind"] == "discovered":
            version_text = source.get("description", version)
        else:
            version_text = f"repository/build revision (`{version}`)"
        upstream = component["upstream"]
        distribution = f"{component['distribution']} ({scope_suffix[component['image_scope']]}); {upstream}"
        locations = "<br>".join(f"`{value}`" if not value.startswith("/") else f"`{value}`" for value in component["notice_locations"])
        sbom = component["sbom"]
        sbom_text = sbom["status"]
        if sbom.get("reason"):
            sbom_text += f": {sbom['reason']}"
        row = [
            component["name"],
            version_text,
            distribution,
            f"{component['license_expression']}. {component['notice_treatment']} {component['trademark_policy']}",
            locations,
            sbom_text,
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in row) + " |")

    lines.extend(
        [
            "",
            "## Direct APT package set",
            "",
            "The following package names are parsed directly from the `apt-get install --no-install-recommends` block. Adding or removing a package changes this generated list and is validated against the image SPDX SBOM:",
            "",
            "```text",
            *apt_packages,
            "```",
            "",
            "## Components not redistributed by the image",
            "",
            "Antigravity CLI, Claude Code and other separately governed agents are not covered by the project Apache-2.0 license merely because Remote Dev can integrate with them. The binding policy and reviewed vendor links are in `optional-agents.md`.",
            "",
            "## Maintenance behavior",
            "",
            "- Version automation refreshes repository-preserved legal documents from exact upstream tags and updates `sources.lock.json` in the same pull request.",
            "- Changed license or NOTICE text is never silently accepted: it appears as a normal reviewed diff.",
            "- A new version/checksum input, direct-download URL, mise runtime, global npm package or SBOM package ecosystem fails validation until it has an inventory owner.",
            "- Runtime-provided Python, Node.js and npm notices are copied from the exact installed artifacts during image construction.",
            "- A new APT package is discovered automatically, rendered in this file and required to appear in the generated SPDX SBOM.",
            "- Optional proprietary integrations remain user-initiated and vendor-sourced; they require a separate terms, privacy, ownership and uninstall review before support is claimed.",
            "",
        ]
    )
    return "\n".join(lines)

def validate_rendered_readme(root: Path, inventory: dict[str, Any], env: dict[str, str], mise: dict[str, dict[str, Any]]) -> None:
    """Fail when the committed human inventory is stale."""
    path = root / "third_party/README.md"
    expected = render_readme(root, inventory, env, mise)
    try:
        actual = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InventoryError(f"generated inventory is missing: {path}") from exc
    if actual != expected:
        raise InventoryError("third_party/README.md is stale; run: python3 scripts/legal-inventory.py render")

def validate_optional_policy(root: Path) -> None:
    """Check mandatory conservative optional-agent policy statements."""
    path = root / "third_party/optional-agents.md"
    text = path.read_text(encoding="utf-8")
    required = [
        "must not contain the vendor binary or package",
        "must never download optional software silently",
        "Antigravity CLI",
        "Claude Code",
        "https://antigravity.google/terms",
        "https://policies.google.com/privacy",
        "--skip-aliases",
        "--skip-path",
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise InventoryError(f"optional-agent policy is missing required text: {missing}")

def refresh_sources(
    root: Path,
    inventory: dict[str, Any],
    env: dict[str, str],
    mise: dict[str, dict[str, Any]],
) -> None:
    """Download exact-tag legal documents and regenerate their source lock."""
    documents = expected_source_documents(inventory, env, mise)
    records: list[dict[str, str]] = []
    opener = urllib.request.build_opener()
    opener.addheaders = [("User-Agent", "remote-dev-containers-legal-inventory/1")]
    for document in documents:
        data: bytes | None = None
        last_error: Exception | None = None
        for attempt in range(4):
            try:
                with opener.open(document.url, timeout=30) as response:
                    if response.status != 200:
                        raise InventoryError(f"unexpected HTTP status {response.status} for {document.url}")
                    data = response.read()
                break
            except (urllib.error.URLError, TimeoutError, InventoryError) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(2**attempt)
        if data is None:
            raise InventoryError(f"failed to download {document.url}: {last_error}")
        if not data:
            raise InventoryError(f"downloaded empty source document: {document.url}")
        destination = root / document.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        records.append(
            {
                "component": document.component_id,
                "git_blob_sha1": git_blob_sha1(data),
                "path": document.path,
                "url": document.url,
                "version": document.version,
            }
        )
        print(f"refreshed {document.path} from {document.url}")
    write_json(root / "third_party/sources.lock.json", {"schema_version": SCHEMA_VERSION, "documents": records})
