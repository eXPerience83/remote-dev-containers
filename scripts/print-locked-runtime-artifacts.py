#!/usr/bin/env python3
"""Print the exact mise.lock runtime artifacts selected for a Docker architecture."""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import NoReturn


ARCH_PLATFORMS = {
    "amd64": "platforms.linux-x64",
    "arm64": "platforms.linux-arm64",
}
TOOLS = ("python", "node", "uv", "yq", "shfmt", "actionlint", "pypi:ruff", "pypi:pytest", "pypi:pre-commit")


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error."""
    raise SystemExit(f"ERROR: {message}")


def main() -> None:
    """Read the lockfile and print the selected runtime artifact fields."""
    if len(sys.argv) != 3:
        fail("usage: print-locked-runtime-artifacts.py <mise.lock> <amd64|arm64>")

    lock_path = Path(sys.argv[1])
    architecture = sys.argv[2]
    platform_key = ARCH_PLATFORMS.get(architecture)
    if platform_key is None:
        fail(f"unsupported Docker architecture: {architecture}")

    try:
        with lock_path.open("rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read {lock_path}: {exc}")

    tools = lock.get("tools")
    if not isinstance(tools, dict):
        fail(f"{lock_path} has no tools table")

    for tool_name in TOOLS:
        entries = tools.get(tool_name)
        expected_count = 2 if tool_name == "python" else 1
        if not isinstance(entries, list) or len(entries) != expected_count:
            fail(f"{lock_path} must contain exactly {expected_count} locked {tool_name} entries")

        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                fail(f"{lock_path} locked {tool_name} entry must be a table")

            version = entry.get("version")
            if not isinstance(version, str) or not version:
                fail(f"{lock_path} locked {tool_name} entry has no version")
            if tool_name == "python":
                expected_line = "3.14." if index == 0 else "3.15."
                if not version.startswith(expected_line):
                    fail(f"locked Python entry {index} must be from {expected_line}x")

            if tool_name.startswith("pypi:"):
                prefix = tool_name.removeprefix("pypi:").upper().replace("-", "_")
                print(f"{prefix}_VERSION={version}")
                print(f"{prefix}_GRAPH_DIGEST={entry['uv']['digest']}")
                continue
            artifact = entry.get(platform_key)
            if not isinstance(artifact, dict):
                fail(f"{lock_path} has no {platform_key} artifact for {tool_name} {version}")

            url = artifact.get("url")
            checksum = artifact.get("checksum")
            if not isinstance(url, str) or not url:
                fail(f"{tool_name} {platform_key} artifact has no URL")
            if not isinstance(checksum, str) or not checksum.startswith("sha256:"):
                fail(f"{tool_name} {platform_key} artifact has no SHA-256 checksum")

            prefix = "PYTHON_315" if tool_name == "python" and index == 1 else tool_name.upper()
            print(f"{prefix}_VERSION={version}")
            print(f"{prefix}_ARTIFACT_URL={url}")
            print(f"{prefix}_ARTIFACT_CHECKSUM={checksum}")


if __name__ == "__main__":
    main()
