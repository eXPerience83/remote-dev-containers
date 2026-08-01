#!/usr/bin/env python3
"""Validate that standalone artifact inspection evidence matches current pins."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Any, NoReturn

REPORT_PATH = Path("third_party/standalone-artifact-inspection.json")
EXPECTED_COMPONENTS = frozenset({"github-cli", "codex-cli", "ttyd", "mise", "uv"})
ARCHITECTURES = ("amd64", "arm64")


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error."""
    raise SystemExit(f"ERROR: {message}")


def read_env(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE environment file and reject duplicate keys."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
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


def require_env(values: dict[str, str], key: str) -> str:
    """Return one non-empty environment value."""
    value = values.get(key)
    if not value:
        fail(f"required pin is missing from versions.env: {key}")
    return value


def load_uv_assets(lock_path: Path, expected_version: str) -> dict[str, dict[str, str]]:
    """Read the exact uv URLs and checksums from mise.lock."""
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read valid {lock_path}: {exc}")

    tools = data.get("tools")
    entries = tools.get("uv") if isinstance(tools, dict) else None
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        fail("mise.lock must contain exactly one [[tools.uv]] record")
    uv = entries[0]
    if uv.get("version") != expected_version:
        fail(
            "uv version differs between versions.env and mise.lock: "
            f"{expected_version} != {uv.get('version')}"
        )

    assets: dict[str, dict[str, str]] = {}
    platform_keys = {
        "amd64": "platforms.linux-x64",
        "arm64": "platforms.linux-arm64",
    }
    for arch, platform_key in platform_keys.items():
        platform = uv.get(platform_key)
        if not isinstance(platform, dict):
            fail(f"mise.lock has no uv platform record for {arch}")
        url = platform.get("url")
        checksum = platform.get("checksum")
        if not isinstance(url, str) or not url.startswith("https://"):
            fail(f"mise.lock has no valid uv URL for {arch}")
        if not isinstance(checksum, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", checksum):
            fail(f"mise.lock has no valid uv checksum for {arch}")
        assets[arch] = {
            "asset_url": url,
            "asset_sha256": checksum.removeprefix("sha256:"),
        }
    return assets


def expected_report(values: dict[str, str], lock_path: Path) -> dict[str, dict[str, Any]]:
    """Build expected version, URL and digest records from repository pins."""
    gh_version = require_env(values, "GH_VERSION")
    codex_version = require_env(values, "CODEX_RELEASE_TAG")
    ttyd_version = require_env(values, "TTYD_VERSION")
    mise_version = require_env(values, "MISE_VERSION")
    uv_version = require_env(values, "UV_VERSION")

    return {
        "github-cli": {
            "version": gh_version,
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/cli/cli/releases/download/v{gh_version}/"
                        f"gh_{gh_version}_linux_amd64.tar.gz"
                    ),
                    "asset_sha256": require_env(values, "GH_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/cli/cli/releases/download/v{gh_version}/"
                        f"gh_{gh_version}_linux_arm64.tar.gz"
                    ),
                    "asset_sha256": require_env(values, "GH_ARM64_SHA256"),
                },
            },
        },
        "codex-cli": {
            "version": codex_version,
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/openai/codex/releases/download/{codex_version}/"
                        "codex-x86_64-unknown-linux-musl.tar.gz"
                    ),
                    "asset_sha256": require_env(values, "CODEX_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/openai/codex/releases/download/{codex_version}/"
                        "codex-aarch64-unknown-linux-musl.tar.gz"
                    ),
                    "asset_sha256": require_env(values, "CODEX_ARM64_SHA256"),
                },
            },
        },
        "ttyd": {
            "version": ttyd_version,
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/tsl0922/ttyd/releases/download/{ttyd_version}/"
                        "ttyd.x86_64"
                    ),
                    "asset_sha256": require_env(values, "TTYD_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/tsl0922/ttyd/releases/download/{ttyd_version}/"
                        "ttyd.aarch64"
                    ),
                    "asset_sha256": require_env(values, "TTYD_ARM64_SHA256"),
                },
            },
        },
        "mise": {
            "version": mise_version,
            "architectures": {
                "amd64": {
                    "asset_url": (
                        f"https://github.com/jdx/mise/releases/download/v{mise_version}/"
                        f"mise-v{mise_version}-linux-x64"
                    ),
                    "asset_sha256": require_env(values, "MISE_AMD64_SHA256"),
                },
                "arm64": {
                    "asset_url": (
                        f"https://github.com/jdx/mise/releases/download/v{mise_version}/"
                        f"mise-v{mise_version}-linux-arm64"
                    ),
                    "asset_sha256": require_env(values, "MISE_ARM64_SHA256"),
                },
            },
        },
        "uv": {
            "version": uv_version,
            "architectures": load_uv_assets(lock_path, uv_version),
        },
    }


def load_report(path: Path) -> dict[str, Any]:
    """Load the inspection report as a JSON object."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid {path}: {exc}")
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        fail(f"unsupported standalone artifact inspection report: {path}")
    components = report.get("components")
    if not isinstance(components, list):
        fail("standalone artifact inspection report has no components array")
    return report


def validate(root: Path) -> None:
    """Validate the report against versions.env and mise.lock."""
    values = read_env(root / "versions.env")
    expected = expected_report(values, root / "mise.lock")
    report = load_report(root / REPORT_PATH)

    components = report["components"]
    by_id: dict[str, dict[str, Any]] = {}
    for component in components:
        if not isinstance(component, dict) or not isinstance(component.get("id"), str):
            fail("standalone artifact inspection contains a malformed component")
        component_id = component["id"]
        if component_id in by_id:
            fail(f"duplicate standalone artifact inspection component: {component_id}")
        by_id[component_id] = component

    if set(by_id) != EXPECTED_COMPONENTS:
        missing = sorted(EXPECTED_COMPONENTS - set(by_id))
        extra = sorted(set(by_id) - EXPECTED_COMPONENTS)
        fail(f"standalone artifact inspection component set differs; missing={missing}, extra={extra}")

    for component_id, expected_component in expected.items():
        actual = by_id[component_id]
        if actual.get("version") != expected_component["version"]:
            fail(
                f"{component_id} inspection version is stale: "
                f"{actual.get('version')} != {expected_component['version']}"
            )
        if actual.get("architecture_legal_sets_equal") is not True:
            fail(f"{component_id} inspection does not confirm equal architecture legal findings")
        architectures = actual.get("architectures")
        if not isinstance(architectures, dict) or set(architectures) != set(ARCHITECTURES):
            fail(f"{component_id} inspection must contain exactly amd64 and arm64")

        for arch in ARCHITECTURES:
            actual_asset = architectures[arch]
            if not isinstance(actual_asset, dict):
                fail(f"{component_id} {arch} inspection record is malformed")
            expected_asset = expected_component["architectures"][arch]
            for field in ("asset_url", "asset_sha256"):
                if actual_asset.get(field) != expected_asset[field]:
                    fail(
                        f"{component_id} {arch} {field} is stale: "
                        f"{actual_asset.get(field)} != {expected_asset[field]}"
                    )
            size = actual_asset.get("asset_size")
            if not isinstance(size, int) or size <= 0:
                fail(f"{component_id} {arch} inspection has no positive asset_size")

    print("Standalone artifact inspection pins: OK")


def main() -> None:
    """Validate committed inspection evidence against repository pins."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = parser.parse_args()
    validate(args.root.resolve())


if __name__ == "__main__":
    main()
