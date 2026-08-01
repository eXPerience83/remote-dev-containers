#!/usr/bin/env python3
"""Refresh bounded inspection evidence for explicitly supported standalone assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

REPORT_PATH = Path("third_party/standalone-artifact-inspection.json")
MARKDOWN_PATH = Path("third_party/standalone-artifact-inspection.md")
ARCHITECTURES = ("amd64", "arm64")
LEGAL_NAME_RE = re.compile(
    r"^(?:LICENSE(?:[._-].*)?|COPYING(?:[._-].*)?|NOTICE(?:[._-].*)?|"
    r"COPYRIGHT(?:[._-].*)?|AUTHORS(?:[._-].*)?)$",
    re.IGNORECASE,
)
COMPONENT_ORDER = ("github-cli", "codex-cli", "ttyd", "mise", "uv")
COMPONENT_NOTICE_PATHS = {
    "github-cli": ("third_party/components/github-cli/LICENSE",),
    "codex-cli": (
        "third_party/components/codex/LICENSE",
        "third_party/components/codex/NOTICE",
    ),
    "ttyd": ("third_party/components/ttyd/LICENSE",),
    "mise": ("third_party/components/mise/LICENSE",),
    "uv": (
        "third_party/components/uv/LICENSE-APACHE-2.0",
        "third_party/components/uv/LICENSE-MIT",
    ),
}


def fail(message: str) -> NoReturn:
    raise SystemExit(f"ERROR: {message}")


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"invalid environment assignment at {path}:{line_number}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            fail(f"invalid environment key at {path}:{line_number}: {key}")
        if key in values:
            fail(f"duplicate environment key in {path}: {key}")
        values[key] = value
    return values


def require(values: dict[str, str], key: str) -> str:
    value = values.get(key)
    if not value:
        fail(f"required pin is missing from versions.env: {key}")
    return value


def load_uv_assets(lock_path: Path, expected_version: str) -> dict[str, dict[str, str]]:
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read valid {lock_path}: {exc}")
    tools = data.get("tools")
    records = tools.get("uv") if isinstance(tools, dict) else None
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        fail("mise.lock must contain exactly one [[tools.uv]] record")
    uv = records[0]
    if uv.get("version") != expected_version:
        fail(
            "uv version differs between versions.env and mise.lock: "
            f"{expected_version} != {uv.get('version')}"
        )
    result: dict[str, dict[str, str]] = {}
    for arch, platform_key in {
        "amd64": "platforms.linux-x64",
        "arm64": "platforms.linux-arm64",
    }.items():
        platform = uv.get(platform_key)
        if not isinstance(platform, dict):
            fail(f"mise.lock has no uv platform record for {arch}")
        url = platform.get("url")
        checksum = platform.get("checksum")
        if not isinstance(url, str) or not url.startswith("https://github.com/astral-sh/uv/"):
            fail(f"mise.lock has no trusted uv URL for {arch}")
        if not isinstance(checksum, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
            fail(f"mise.lock has no valid uv checksum for {arch}")
        result[arch] = {
            "asset_url": url,
            "asset_sha256": checksum.removeprefix("sha256:"),
        }
    return result


def expected_components(root: Path) -> dict[str, dict[str, Any]]:
    values = read_env(root / "versions.env")
    gh_version = require(values, "GH_VERSION")
    codex_version = require(values, "CODEX_RELEASE_TAG")
    ttyd_version = require(values, "TTYD_VERSION")
    mise_version = require(values, "MISE_VERSION")
    uv_version = require(values, "UV_VERSION")
    return {
        "github-cli": {
            "version": gh_version,
            "packaging": "tar.gz",
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/cli/cli/releases/download/v{gh_version}/"
                        f"gh_{gh_version}_linux_amd64.tar.gz"
                    ),
                    "asset_sha256": require(values, "GH_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/cli/cli/releases/download/v{gh_version}/"
                        f"gh_{gh_version}_linux_arm64.tar.gz"
                    ),
                    "asset_sha256": require(values, "GH_ARM64_SHA256"),
                },
            },
        },
        "codex-cli": {
            "version": codex_version,
            "packaging": "tar.gz",
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/openai/codex/releases/download/{codex_version}/"
                        "codex-x86_64-unknown-linux-musl.tar.gz"
                    ),
                    "asset_sha256": require(values, "CODEX_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/openai/codex/releases/download/{codex_version}/"
                        "codex-aarch64-unknown-linux-musl.tar.gz"
                    ),
                    "asset_sha256": require(values, "CODEX_ARM64_SHA256"),
                },
            },
        },
        "ttyd": {
            "version": ttyd_version,
            "packaging": "raw-binary",
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/tsl0922/ttyd/releases/download/{ttyd_version}/"
                        "ttyd.x86_64"
                    ),
                    "asset_sha256": require(values, "TTYD_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/tsl0922/ttyd/releases/download/{ttyd_version}/"
                        "ttyd.aarch64"
                    ),
                    "asset_sha256": require(values, "TTYD_ARM64_SHA256"),
                },
            },
        },
        "mise": {
            "version": mise_version,
            "packaging": "raw-binary",
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/jdx/mise/releases/download/v{mise_version}/"
                        f"mise-v{mise_version}-linux-x64"
                    ),
                    "asset_sha256": require(values, "MISE_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/jdx/mise/releases/download/v{mise_version}/"
                        f"mise-v{mise_version}-linux-arm64"
                    ),
                    "asset_sha256": require(values, "MISE_ARM64_SHA256"),
                },
            },
        },
        "uv": {
            "version": uv_version,
            "packaging": "tar.gz",
            "architectures": load_uv_assets(root / "mise.lock", uv_version),
        },
    }


def fingerprint_file(path: Path) -> dict[str, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        fail(f"cannot read repository notice {path}: {exc}")
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def repository_notices(root: Path, component_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for relative in COMPONENT_NOTICE_PATHS[component_id]:
        fingerprint = fingerprint_file(root / relative)
        records.append({"path": relative, **fingerprint})
    return records


def load_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid {path}: {exc}")
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        fail(f"unsupported standalone artifact inspection report: {path}")
    components = report.get("components")
    if not isinstance(components, list):
        fail(f"standalone artifact inspection report has no components array: {path}")
    return report


def component_is_current(
    actual: dict[str, Any] | None,
    expected: dict[str, Any],
    notices: list[dict[str, Any]],
) -> bool:
    if not isinstance(actual, dict):
        return False
    if actual.get("version") != expected["version"]:
        return False
    if actual.get("packaging") != expected["packaging"]:
        return False
    if actual.get("repository_notices") != notices:
        return False
    if actual.get("architecture_legal_sets_equal") is not True:
        return False
    architectures = actual.get("architectures")
    if not isinstance(architectures, dict) or set(architectures) != set(ARCHITECTURES):
        return False
    for arch in ARCHITECTURES:
        actual_asset = architectures.get(arch)
        expected_asset = expected["architectures"][arch]
        if not isinstance(actual_asset, dict):
            return False
        if actual_asset.get("asset_url") != expected_asset["asset_url"]:
            return False
        if actual_asset.get("asset_sha256") != expected_asset["asset_sha256"]:
            return False
        if not isinstance(actual_asset.get("asset_size"), int) or actual_asset["asset_size"] <= 0:
            return False
        if "archive_member_count" not in actual_asset:
            return False
        if not isinstance(actual_asset.get("legal_members"), list):
            return False
    return True


def download_verified(url: str, expected_sha256: str, destination: Path) -> None:
    if not url.startswith("https://github.com/"):
        fail(f"refusing non-GitHub standalone asset URL: {url}")
    headers = {"User-Agent": "remote-dev-containers-standalone-inspection"}
    token = os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    last_error: Exception | None = None
    for attempt in range(1, 4):
        digest = hashlib.sha256()
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
            actual = digest.hexdigest()
            if actual != expected_sha256:
                fail(f"SHA-256 mismatch for {url}: {actual} != {expected_sha256}")
            return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            destination.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(attempt)
    fail(f"cannot download {url}: {last_error}")


def legal_member_record(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    notices: list[dict[str, Any]],
) -> dict[str, Any]:
    stream = archive.extractfile(member)
    if stream is None:
        fail(f"cannot read archive member {member.name}")
    data = stream.read()
    record: dict[str, Any] = {
        "path": member.name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    for notice in notices:
        if record["sha256"] == notice["sha256"] and record["size"] == notice["size"]:
            record["matches_repository_notice"] = notice["path"]
            break
    return record


def inspect_asset(
    path: Path,
    packaging: str,
    notices: list[dict[str, Any]],
) -> dict[str, Any]:
    if packaging == "raw-binary":
        return {
            "asset_size": path.stat().st_size,
            "archive_member_count": None,
            "legal_members": [],
        }
    if packaging != "tar.gz":
        fail(f"unsupported bounded standalone packaging: {packaging}")
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            legal_members = [
                legal_member_record(archive, member, notices)
                for member in members
                if member.isfile() and LEGAL_NAME_RE.fullmatch(Path(member.name).name)
            ]
    except (OSError, tarfile.TarError) as exc:
        fail(f"cannot inspect tar.gz asset {path}: {exc}")
    legal_members.sort(key=lambda item: item["path"])
    return {
        "asset_size": path.stat().st_size,
        "archive_member_count": len(members),
        "legal_members": legal_members,
    }


def normalized_legal_set(asset: dict[str, Any]) -> tuple[tuple[Any, ...], ...]:
    normalized = []
    for member in asset.get("legal_members", []):
        normalized.append(
            (
                Path(member["path"]).name.casefold(),
                member["sha256"],
                member["size"],
                member.get("matches_repository_notice"),
            )
        )
    return tuple(sorted(normalized))


def inspect_component(
    component_id: str,
    expected: dict[str, Any],
    notices: list[dict[str, Any]],
    workdir: Path,
) -> dict[str, Any]:
    architectures: dict[str, dict[str, Any]] = {}
    for arch in ARCHITECTURES:
        expected_asset = expected["architectures"][arch]
        destination = workdir / f"{component_id}-{arch}.asset"
        print(f"Inspecting {component_id} {expected['version']} {arch}")
        download_verified(
            expected_asset["asset_url"],
            expected_asset["asset_sha256"],
            destination,
        )
        inspected = inspect_asset(destination, expected["packaging"], notices)
        print(
            f"  size={inspected['asset_size']} members={inspected['archive_member_count']} "
            f"legal={len(inspected['legal_members'])}"
        )
        architectures[arch] = {**expected_asset, **inspected}
        destination.unlink(missing_ok=True)
    equal = normalized_legal_set(architectures["amd64"]) == normalized_legal_set(
        architectures["arm64"]
    )
    return {
        "id": component_id,
        "version": expected["version"],
        "packaging": expected["packaging"],
        "repository_notices": notices,
        "architecture_legal_sets_equal": equal,
        "architectures": architectures,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Standalone artifact inspection",
        "",
        (
            "This is a bounded inspection of the exact AMD64 and ARM64 release assets "
            "pinned by the repository. It records whether the distributed archive itself "
            "contains license-like files; repository-preserved notices remain the "
            "authoritative documents shipped in the image."
        ),
        "",
        "| Component | Version | Packaging | Legal files inside asset | Repository notices |",
        "|---|---:|---|---|---|",
    ]
    for component in report["components"]:
        legal_names = sorted(
            {
                Path(member["path"]).name
                for asset in component["architectures"].values()
                for member in asset["legal_members"]
            }
        )
        notice_names = [Path(item["path"]).name for item in component["repository_notices"]]
        lines.append(
            f"| {component['id']} | `{component['version']}` | {component['packaging']} | "
            f"{', '.join(legal_names) if legal_names else 'None'} | "
            f"{', '.join(notice_names)} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "- A raw executable cannot carry a separate license file as an archive "
                "member, so its exact repository license is preserved alongside the image."
            ),
            (
                "- An archive with no license-like member likewise relies on the exact "
                "version-specific repository notice recorded in `third_party/inventory.json`."
            ),
            (
                "- When an archive includes a legal file, the JSON report records its "
                "content hash and whether it exactly matches a preserved repository notice."
            ),
            (
                "- The report is inspection evidence for the pinned versions, not a general "
                "binary or dependency-license scanner."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def refresh(root: Path) -> bool:
    report_path = root / REPORT_PATH
    report = load_report(report_path)
    expected = expected_components(root)
    existing_by_id = {
        item.get("id"): item
        for item in report["components"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    refreshed: list[dict[str, Any]] = []
    changed = False
    with tempfile.TemporaryDirectory(prefix="standalone-inspection-") as temp:
        workdir = Path(temp)
        for component_id in COMPONENT_ORDER:
            notices = repository_notices(root, component_id)
            current = existing_by_id.get(component_id)
            if component_is_current(current, expected[component_id], notices):
                refreshed.append(current)
                continue
            changed = True
            component = inspect_component(
                component_id,
                expected[component_id],
                notices,
                workdir,
            )
            if component["architecture_legal_sets_equal"] is not True:
                fail(f"{component_id} legal-file findings differ between amd64 and arm64")
            refreshed.append(component)
    new_report = {
        "schema_version": 1,
        "scope": "Exact amd64 and arm64 standalone assets distributed by the current images",
        "components": refreshed,
    }
    json_text = json.dumps(new_report, indent=2, ensure_ascii=False) + "\n"
    markdown_text = render_markdown(new_report)
    if report_path.read_text(encoding="utf-8") != json_text:
        changed = True
        report_path.write_text(json_text, encoding="utf-8")
    markdown_path = root / MARKDOWN_PATH
    current_markdown = (
        markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    )
    if current_markdown != markdown_text:
        changed = True
        markdown_path.write_text(markdown_text, encoding="utf-8")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = parser.parse_args()
    changed = refresh(args.root.resolve())
    print(
        "Standalone artifact inspection refreshed."
        if changed
        else "Standalone artifact inspection already current."
    )


if __name__ == "__main__":
    main()
