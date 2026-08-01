#!/usr/bin/env python3
"""Inspect the exact current standalone release assets for bundled legal files."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[2]
MAX_ASSET_BYTES = 160 * 1024 * 1024
LEGAL_NAME = re.compile(r"^(?:licen[cs]e|notice|copying|copyright)(?:[._-].*)?$", re.I)
USER_AGENT = "remote-dev-containers standalone artifact inspection"


def fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


def parse_versions() -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate((ROOT / "versions.env").read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"versions.env:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key] = value
    return values


def parse_uv_assets() -> dict[str, dict[str, str]]:
    text = (ROOT / "mise.lock").read_text(encoding="utf-8")
    records: dict[str, dict[str, str]] = {}
    section = ""
    checksum = ""
    url = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[tools.uv."):
            if section and checksum and url:
                records[section] = {"url": url, "sha256": checksum.removeprefix("sha256:")}
            section = "arm64" if "linux-arm64" in line else "amd64" if "linux-x64" in line else ""
            checksum = ""
            url = ""
        elif section and line.startswith("checksum = "):
            checksum = line.split('"', 2)[1]
        elif section and line.startswith("url = ") and "url_api" not in line:
            url = line.split('"', 2)[1]
    if section and checksum and url:
        records[section] = {"url": url, "sha256": checksum.removeprefix("sha256:")}
    if set(records) != {"amd64", "arm64"}:
        fail("could not resolve both uv assets from mise.lock")
    return records


def allowed_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        fail(f"asset URL must be credential-free HTTPS: {url}")
    if host != "github.com" and not host.endswith(".githubusercontent.com"):
        fail(f"asset URL host is not approved: {url}")


def download(url: str, expected_sha256: str, destination: Path) -> int:
    allowed_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        allowed_url(response.geturl())
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ASSET_BYTES:
                fail(f"asset exceeds {MAX_ASSET_BYTES} bytes: {url}")
            digest.update(chunk)
            handle.write(chunk)
    actual = digest.hexdigest()
    if actual != expected_sha256:
        fail(f"SHA-256 mismatch for {url}: expected {expected_sha256}, got {actual}")
    return size


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def repository_notices(paths: list[str]) -> list[dict[str, Any]]:
    notices: list[dict[str, Any]] = []
    for relative in paths:
        path = ROOT / "third_party" / relative
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"repository notice is missing: third_party/{relative}")
        notices.append(
            {
                "path": f"third_party/{relative}",
                "sha256": file_sha256(path),
                "size": path.stat().st_size,
            }
        )
    return notices


def inspect_archive(path: Path, notices: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    notice_hashes = {item["sha256"]: item["path"] for item in notices}
    legal: list[dict[str, Any]] = []
    member_count = 0
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            member_count += 1
            if not LEGAL_NAME.match(Path(member.name).name):
                continue
            if member.size > 2 * 1024 * 1024:
                fail(f"unexpectedly large legal member: {member.name}")
            extracted = archive.extractfile(member)
            if extracted is None:
                fail(f"cannot read legal member: {member.name}")
            content = extracted.read()
            digest = hashlib.sha256(content).hexdigest()
            legal.append(
                {
                    "path": member.name,
                    "sha256": digest,
                    "size": len(content),
                    "matches_repository_notice": notice_hashes.get(digest),
                }
            )
    return member_count, sorted(legal, key=lambda item: item["path"])


def component_definitions(values: dict[str, str], uv: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "id": "github-cli",
            "version": values["GH_VERSION"],
            "kind": "tar.gz",
            "notices": ["components/github-cli/LICENSE"],
            "assets": {
                "amd64": {
                    "url": f"https://github.com/cli/cli/releases/download/v{values['GH_VERSION']}/gh_{values['GH_VERSION']}_linux_amd64.tar.gz",
                    "sha256": values["GH_AMD64_SHA256"],
                },
                "arm64": {
                    "url": f"https://github.com/cli/cli/releases/download/v{values['GH_VERSION']}/gh_{values['GH_VERSION']}_linux_arm64.tar.gz",
                    "sha256": values["GH_ARM64_SHA256"],
                },
            },
        },
        {
            "id": "codex-cli",
            "version": values["CODEX_RELEASE_TAG"],
            "kind": "tar.gz",
            "notices": ["components/codex/LICENSE", "components/codex/NOTICE"],
            "assets": {
                "amd64": {
                    "url": f"https://github.com/openai/codex/releases/download/{values['CODEX_RELEASE_TAG']}/codex-x86_64-unknown-linux-musl.tar.gz",
                    "sha256": values["CODEX_AMD64_SHA256"],
                },
                "arm64": {
                    "url": f"https://github.com/openai/codex/releases/download/{values['CODEX_RELEASE_TAG']}/codex-aarch64-unknown-linux-musl.tar.gz",
                    "sha256": values["CODEX_ARM64_SHA256"],
                },
            },
        },
        {
            "id": "ttyd",
            "version": values["TTYD_VERSION"],
            "kind": "raw-binary",
            "notices": ["components/ttyd/LICENSE"],
            "assets": {
                "amd64": {
                    "url": f"https://github.com/tsl0922/ttyd/releases/download/{values['TTYD_VERSION']}/ttyd.x86_64",
                    "sha256": values["TTYD_AMD64_SHA256"],
                },
                "arm64": {
                    "url": f"https://github.com/tsl0922/ttyd/releases/download/{values['TTYD_VERSION']}/ttyd.aarch64",
                    "sha256": values["TTYD_ARM64_SHA256"],
                },
            },
        },
        {
            "id": "mise",
            "version": values["MISE_VERSION"],
            "kind": "raw-binary",
            "notices": ["components/mise/LICENSE"],
            "assets": {
                "amd64": {
                    "url": f"https://github.com/jdx/mise/releases/download/v{values['MISE_VERSION']}/mise-v{values['MISE_VERSION']}-linux-x64",
                    "sha256": values["MISE_AMD64_SHA256"],
                },
                "arm64": {
                    "url": f"https://github.com/jdx/mise/releases/download/v{values['MISE_VERSION']}/mise-v{values['MISE_VERSION']}-linux-arm64",
                    "sha256": values["MISE_ARM64_SHA256"],
                },
            },
        },
        {
            "id": "uv",
            "version": values["UV_VERSION"],
            "kind": "tar.gz",
            "notices": ["components/uv/LICENSE-APACHE-2.0", "components/uv/LICENSE-MIT"],
            "assets": uv,
        },
    ]


def main() -> None:
    values = parse_versions()
    components = component_definitions(values, parse_uv_assets())
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="standalone-inspection-") as directory:
        scratch = Path(directory)
        for component in components:
            notices = repository_notices(component["notices"])
            arch_results: dict[str, Any] = {}
            legal_sets: list[list[tuple[str, str]]] = []
            for arch, asset in component["assets"].items():
                path = scratch / f"{component['id']}-{arch}"
                size = download(asset["url"], asset["sha256"], path)
                legal_members: list[dict[str, Any]] = []
                member_count: int | None = None
                if component["kind"] == "tar.gz":
                    member_count, legal_members = inspect_archive(path, notices)
                    legal_sets.append(
                        [(Path(item["path"]).name, item["sha256"]) for item in legal_members]
                    )
                arch_results[arch] = {
                    "asset_url": asset["url"],
                    "asset_sha256": asset["sha256"],
                    "asset_size": size,
                    "archive_member_count": member_count,
                    "legal_members": legal_members,
                }
            results.append(
                {
                    "id": component["id"],
                    "version": component["version"],
                    "packaging": component["kind"],
                    "repository_notices": notices,
                    "architecture_legal_sets_equal": len(legal_sets) < 2 or legal_sets[0] == legal_sets[1],
                    "architectures": arch_results,
                }
            )

    report = {
        "schema_version": 1,
        "scope": "Exact amd64 and arm64 standalone assets distributed by the current images",
        "components": results,
    }
    output = ROOT / "third_party" / "standalone-artifact-inspection.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Standalone artifact inspection",
        "",
        "This is a bounded inspection of the exact AMD64 and ARM64 release assets pinned by the repository. It records whether the distributed archive itself contains license-like files; repository-preserved notices remain the authoritative documents shipped in the image.",
        "",
        "| Component | Version | Packaging | Legal files inside asset | Repository notices |",
        "|---|---:|---|---|---|",
    ]
    for component in results:
        amd64 = component["architectures"]["amd64"]
        legal = amd64["legal_members"]
        legal_text = ", ".join(Path(item["path"]).name for item in legal) or "None"
        notices_text = ", ".join(Path(item["path"]).name for item in component["repository_notices"])
        lines.append(
            f"| {component['id']} | `{component['version']}` | {component['packaging']} | {legal_text} | {notices_text} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- A raw executable cannot carry a separate license file as an archive member, so its exact repository license is preserved alongside the image.",
            "- An archive with no license-like member likewise relies on the exact version-specific repository notice recorded in `third_party/inventory.json`.",
            "- When an archive includes a legal file, the JSON report records its content hash and whether it exactly matches a preserved repository notice.",
            "- The report is inspection evidence for the pinned versions, not a general binary or dependency-license scanner.",
        ]
    )
    (ROOT / "third_party" / "standalone-artifact-inspection.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
