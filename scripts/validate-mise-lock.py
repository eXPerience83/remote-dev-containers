#!/usr/bin/env python3
"""Validate committed mise runtime configuration and artifact lock data."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, NoReturn

ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PLATFORMS = ("linux-x64", "linux-arm64")
EXPECTED_BACKENDS = {
    "python": "core:python",
    "node": "core:node",
    "uv": "aqua:astral-sh/uv",
}


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error message."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_env(path: Path) -> dict[str, str]:
    """Load a simple NAME=value environment file without shell evaluation."""
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = ASSIGNMENT_RE.fullmatch(line)
        if not match:
            fail(f"{path}:{number} is not a simple NAME=value assignment")
        values[match.group(1)] = match.group(2)
    return values


def load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML document or fail with the original parse error."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read valid TOML from {path}: {exc}")


def expect_string(mapping: dict[str, Any], key: str, context: str) -> str:
    """Return a required non-empty string from a TOML mapping."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        fail(f"{context}.{key} must be a non-empty string")
    return value


def platform_info(entry: dict[str, Any], platform: str, tool: str) -> dict[str, Any]:
    """Return one locked platform artifact mapping for a managed tool."""
    key = f"platforms.{platform}"
    value = entry.get(key)
    if not isinstance(value, dict):
        fail(f"mise.lock has no {tool} artifact entry for {platform}")
    return value


def validate_url(tool: str, version: str, platform: str, url: str) -> None:
    """Require an artifact URL that matches the approved upstream layout."""
    arch = {"linux-x64": "x86_64", "linux-arm64": "aarch64"}[platform]
    if tool == "node":
        node_arch = "x64" if platform == "linux-x64" else "arm64"
        expected = (
            f"https://nodejs.org/dist/v{version}/"
            f"node-v{version}-linux-{node_arch}.tar.gz"
        )
        if url != expected:
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return

    if tool == "python":
        pattern = re.compile(
            rf"^https://github\.com/astral-sh/python-build-standalone/releases/download/"
            rf"(?P<date>[0-9]{{8}})/cpython-{re.escape(version)}\+(?P=date)-{arch}-unknown-linux-gnu-"
            rf"install_only_stripped\.tar\.gz$"
        )
        if not pattern.fullmatch(url):
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return

    if tool == "uv":
        expected = (
            f"https://github.com/astral-sh/uv/releases/download/{version}/"
            f"uv-{arch}-unknown-linux-musl.tar.gz"
        )
        if url != expected:
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return

    fail(f"no URL policy defined for mise tool {tool}")


def expected_versions_from_env(env: dict[str, str]) -> dict[str, str]:
    """Extract required managed-runtime versions from versions.env."""
    expected_versions = {
        "python": env.get("PYTHON_VERSION", ""),
        "node": env.get("NODE_VERSION", ""),
        "uv": env.get("UV_VERSION", ""),
    }
    for tool, version in expected_versions.items():
        if not version:
            fail(f"versions.env has no version for {tool}")
    return expected_versions


def validate_mise_config(config: dict[str, Any], expected_versions: dict[str, str]) -> None:
    """Validate mise settings, managed tools, and version coherence."""
    settings = config.get("settings")
    if not isinstance(settings, dict):
        fail("mise.toml must contain [settings]")
    if settings.get("lockfile") is not True:
        fail("mise.toml must enable settings.lockfile")
    if settings.get("locked_verify_provenance") is not True:
        fail("mise.toml must enable settings.locked_verify_provenance")
    configured_platforms = settings.get("lockfile_platforms")
    if configured_platforms != list(PLATFORMS):
        fail(
            "mise.toml settings.lockfile_platforms must be exactly "
            f"{list(PLATFORMS)!r}, got {configured_platforms!r}"
        )

    configured_tools = config.get("tools")
    if not isinstance(configured_tools, dict):
        fail("mise.toml must contain [tools]")
    if set(configured_tools) != set(expected_versions):
        fail(
            "mise.toml must define exactly the managed runtimes "
            f"{sorted(expected_versions)}, got {sorted(configured_tools)}"
        )
    for tool, expected_version in expected_versions.items():
        if configured_tools.get(tool) != expected_version:
            fail(
                f"mise.toml {tool} version {configured_tools.get(tool)!r} does not match "
                f"versions.env {expected_version!r}"
            )


def validate_artifact(
    tool: str, version: str, platform: str, artifact: dict[str, Any]
) -> None:
    """Validate one platform-specific checksum, URL, and provenance record."""
    checksum = expect_string(artifact, "checksum", f"mise.lock tools.{tool}.{platform}")
    if not SHA256_RE.fullmatch(checksum):
        fail(
            f"mise.lock {tool} checksum for {platform} must be an exact "
            f"lowercase SHA-256: {checksum}"
        )
    url = expect_string(artifact, "url", f"mise.lock tools.{tool}.{platform}")
    validate_url(tool, version, platform, url)
    if tool in {"python", "uv"} and artifact.get("provenance") != "github-attestations":
        fail(
            f"mise.lock {tool} artifact for {platform} must require "
            "GitHub artifact attestations"
        )


def validate_tool_entry(
    tool: str,
    expected_version: str,
    entries: Any,
) -> None:
    """Validate one managed tool entry and all required platform artifacts."""
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
        fail(f"mise.lock must contain exactly one {tool} entry")
    entry = entries[0]
    version = expect_string(entry, "version", f"mise.lock tools.{tool}")
    backend = expect_string(entry, "backend", f"mise.lock tools.{tool}")
    if version != expected_version:
        fail(
            f"mise.lock {tool} version {version!r} does not match "
            f"versions.env {expected_version!r}"
        )
    if backend != EXPECTED_BACKENDS[tool]:
        fail(
            f"mise.lock {tool} backend {backend!r} does not match "
            f"{EXPECTED_BACKENDS[tool]!r}"
        )

    locked_platforms = {
        key.removeprefix("platforms.")
        for key, value in entry.items()
        if key.startswith("platforms.") and isinstance(value, dict)
    }
    if locked_platforms != set(PLATFORMS):
        fail(
            f"mise.lock {tool} platforms must be exactly {sorted(PLATFORMS)}, "
            f"got {sorted(locked_platforms)}"
        )

    for platform in PLATFORMS:
        validate_artifact(tool, version, platform, platform_info(entry, platform, tool))


def validate_lock(lock: dict[str, Any], expected_versions: dict[str, str]) -> None:
    """Validate the lockfile tool set and each locked runtime entry."""
    lock_tools = lock.get("tools")
    if not isinstance(lock_tools, dict):
        fail("mise.lock must contain tool entries")
    if set(lock_tools) != set(expected_versions):
        fail(
            "mise.lock must contain exactly the managed runtimes "
            f"{sorted(expected_versions)}, got {sorted(lock_tools)}"
        )

    for tool, expected_version in expected_versions.items():
        validate_tool_entry(tool, expected_version, lock_tools.get(tool))


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for repository-root selection."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args()


def main() -> int:
    """Load repository inputs, run all lock validations, and report success."""
    root = parse_args().root.resolve()
    expected_versions = expected_versions_from_env(load_env(root / "versions.env"))
    validate_mise_config(load_toml(root / "mise.toml"), expected_versions)
    validate_lock(load_toml(root / "mise.lock"), expected_versions)

    print(
        "mise runtime lock is coherent for "
        + ", ".join(f"{tool} {version}" for tool, version in expected_versions.items())
        + " on linux-x64 and linux-arm64, with locked provenance re-verification enabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
