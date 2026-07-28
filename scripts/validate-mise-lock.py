#!/usr/bin/env python3
"""Validate committed mise runtime configuration and artifact lock data."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any, NoReturn, cast

ASSIGNMENT_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UV_API_URL_RE = re.compile(
    r"^https://api\.github\.com/repos/astral-sh/uv/releases/assets/[1-9][0-9]*$"
)
PLATFORMS = ("linux-x64", "linux-arm64")
EXPECTED_BACKENDS = {
    "python": "core:python",
    "node": "core:node",
    "uv": "aqua:astral-sh/uv",
}
CONFIG_TOP_LEVEL_KEYS = {"settings", "tools"}
CONFIG_SETTING_KEYS = {
    "lockfile",
    "locked_verify_provenance",
    "lockfile_platforms",
}
LOCK_TOP_LEVEL_KEYS = {"tools"}
TOOL_ENTRY_KEYS = {
    "version",
    "backend",
    *(f"platforms.{platform}" for platform in PLATFORMS),
}
ARTIFACT_KEYS = {
    "node": {"checksum", "url"},
    "python": {"checksum", "url", "provenance"},
    "uv": {"checksum", "url", "url_api", "provenance"},
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


def require_exact_keys(
    mapping: dict[str, Any], expected: set[str], context: str
) -> None:
    """Reject missing or unknown keys in a security-sensitive TOML mapping."""
    actual = set(mapping)
    if actual != expected:
        fail(
            f"{context} keys must be exactly {sorted(expected)}, "
            f"got {sorted(actual)}"
        )


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
        fail(f"mise.lock has no valid {tool} artifact mapping for {platform}")
    return cast(dict[str, Any], value)


def validate_url(tool: str, version: str, platform: str, url: str) -> str | None:
    """Require an approved artifact URL and return Python's build date when present."""
    arch = {"linux-x64": "x86_64", "linux-arm64": "aarch64"}[platform]
    if tool == "node":
        node_arch = "x64" if platform == "linux-x64" else "arm64"
        expected = (
            f"https://nodejs.org/dist/v{version}/"
            f"node-v{version}-linux-{node_arch}.tar.gz"
        )
        if url != expected:
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return None

    if tool == "python":
        pattern = re.compile(
            rf"^https://github\.com/astral-sh/python-build-standalone/releases/download/"
            rf"(?P<date>[0-9]{{8}})/cpython-{re.escape(version)}\+(?P=date)-{arch}-unknown-linux-gnu-"
            rf"install_only_stripped\.tar\.gz$"
        )
        match = pattern.fullmatch(url)
        if match is None:
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return match.group("date")

    if tool == "uv":
        expected = (
            f"https://github.com/astral-sh/uv/releases/download/{version}/"
            f"uv-{arch}-unknown-linux-musl.tar.gz"
        )
        if url != expected:
            fail(f"mise.lock {tool} URL for {platform} is unexpected: {url}")
        return None

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
    require_exact_keys(config, CONFIG_TOP_LEVEL_KEYS, "mise.toml top-level")

    settings = config.get("settings")
    if not isinstance(settings, dict):
        fail("mise.toml must contain [settings]")
    settings = cast(dict[str, Any], settings)
    require_exact_keys(settings, CONFIG_SETTING_KEYS, "mise.toml settings")
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
    configured_tools = cast(dict[str, Any], configured_tools)
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
) -> str | None:
    """Validate one artifact and return its cross-platform build identifier."""
    require_exact_keys(
        artifact,
        ARTIFACT_KEYS[tool],
        f"mise.lock tools.{tool}.{platform}",
    )
    checksum = expect_string(artifact, "checksum", f"mise.lock tools.{tool}.{platform}")
    if not SHA256_RE.fullmatch(checksum):
        fail(
            f"mise.lock {tool} checksum for {platform} must be an exact "
            f"lowercase SHA-256: {checksum}"
        )
    url = expect_string(artifact, "url", f"mise.lock tools.{tool}.{platform}")
    build_identifier = validate_url(tool, version, platform, url)

    if tool in {"python", "uv"} and artifact.get("provenance") != "github-attestations":
        fail(
            f"mise.lock {tool} artifact for {platform} must require "
            "GitHub artifact attestations"
        )
    if tool == "uv":
        url_api = expect_string(
            artifact, "url_api", f"mise.lock tools.{tool}.{platform}"
        )
        if not UV_API_URL_RE.fullmatch(url_api):
            fail(f"mise.lock uv API URL for {platform} is unexpected: {url_api}")

    return build_identifier


def validate_tool_entry(
    tool: str,
    expected_version: str,
    entries: object,
) -> None:
    """Validate one managed tool entry and all required platform artifacts."""
    if not isinstance(entries, list) or len(entries) != 1:
        fail(f"mise.lock must contain exactly one {tool} entry")
    raw_entry = entries[0]
    if not isinstance(raw_entry, dict):
        fail(f"mise.lock must contain exactly one {tool} entry")
    entry = cast(dict[str, Any], raw_entry)
    require_exact_keys(entry, TOOL_ENTRY_KEYS, f"mise.lock tools.{tool}")

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
        for key in entry
        if key.startswith("platforms.")
    }
    if locked_platforms != set(PLATFORMS):
        fail(
            f"mise.lock {tool} platforms must be exactly {sorted(PLATFORMS)}, "
            f"got {sorted(locked_platforms)}"
        )

    build_identifiers: list[str] = []
    uv_api_urls: list[str] = []
    for platform in PLATFORMS:
        artifact = platform_info(entry, platform, tool)
        build_identifier = validate_artifact(tool, version, platform, artifact)
        if build_identifier is not None:
            build_identifiers.append(build_identifier)
        if tool == "uv":
            uv_api_urls.append(
                expect_string(artifact, "url_api", f"mise.lock tools.{tool}.{platform}")
            )

    if tool == "python" and len(set(build_identifiers)) != 1:
        fail(
            "mise.lock python artifacts must use one cross-platform build date, "
            f"got {sorted(set(build_identifiers))}"
        )
    if tool == "uv" and len(set(uv_api_urls)) != len(uv_api_urls):
        fail("mise.lock uv artifacts must use distinct GitHub release asset API URLs")


def validate_lock(lock: dict[str, Any], expected_versions: dict[str, str]) -> None:
    """Validate the lockfile tool set and each locked runtime entry."""
    require_exact_keys(lock, LOCK_TOP_LEVEL_KEYS, "mise.lock top-level")
    lock_tools = lock.get("tools")
    if not isinstance(lock_tools, dict):
        fail("mise.lock must contain tool entries")
    lock_tools = cast(dict[str, Any], lock_tools)
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
