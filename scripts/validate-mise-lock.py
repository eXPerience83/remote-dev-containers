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


def fail(message: str) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_env(path: Path) -> dict[str, str]:
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
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read valid TOML from {path}: {exc}")


def expect_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        fail(f"{context}.{key} must be a non-empty string")
    return value


def platform_info(entry: dict[str, Any], platform: str, tool: str) -> dict[str, Any]:
    key = f"platforms.{platform}"
    value = entry.get(key)
    if not isinstance(value, dict):
        fail(f"mise.lock has no {tool} artifact entry for {platform}")
    return value


def validate_url(tool: str, version: str, platform: str, url: str) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    env = load_env(root / "versions.env")
    expected_versions = {
        "python": env.get("PYTHON_VERSION", ""),
        "node": env.get("NODE_VERSION", ""),
        "uv": env.get("UV_VERSION", ""),
    }
    for tool, version in expected_versions.items():
        if not version:
            fail(f"versions.env has no version for {tool}")

    config = load_toml(root / "mise.toml")
    settings = config.get("settings")
    if not isinstance(settings, dict):
        fail("mise.toml must contain [settings]")
    if settings.get("lockfile") is not True:
        fail("mise.toml must enable settings.lockfile")
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

    lock = load_toml(root / "mise.lock")
    lock_tools = lock.get("tools")
    if not isinstance(lock_tools, dict):
        fail("mise.lock must contain tool entries")
    if set(lock_tools) != set(expected_versions):
        fail(
            "mise.lock must contain exactly the managed runtimes "
            f"{sorted(expected_versions)}, got {sorted(lock_tools)}"
        )

    expected_backends = {
        "python": "core:python",
        "node": "core:node",
        "uv": "aqua:astral-sh/uv",
    }
    for tool, expected_version in expected_versions.items():
        entries = lock_tools.get(tool)
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
        if backend != expected_backends[tool]:
            fail(
                f"mise.lock {tool} backend {backend!r} does not match "
                f"{expected_backends[tool]!r}"
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
            artifact = platform_info(entry, platform, tool)
            checksum = expect_string(
                artifact, "checksum", f"mise.lock tools.{tool}.{platform}"
            )
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

    print(
        "mise runtime lock is coherent for "
        + ", ".join(f"{tool} {version}" for tool, version in expected_versions.items())
        + " on linux-x64 and linux-arm64."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
