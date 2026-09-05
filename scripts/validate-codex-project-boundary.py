#!/usr/bin/env python3
"""Fail closed unless Codex's effective shell policy preserves the Git ceiling."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time
from typing import Any

MAX_LINE_BYTES = 1024 * 1024
STARTUP_TIMEOUT_SECONDS = 6.0
REQUIRED_ENV = "GIT_CEILING_DIRECTORIES"


class BoundaryError(RuntimeError):
    pass


def _write_message(process: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise BoundaryError("Codex configuration probe stdin is unavailable")
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_response(process: subprocess.Popen[str], request_id: int) -> dict[str, Any]:
    if process.stdout is None:
        raise BoundaryError("Codex configuration probe stdout is unavailable")
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BoundaryError("Codex configuration probe timed out")
        ready, _, _ = select.select([process.stdout], [], [], remaining)
        if not ready:
            raise BoundaryError("Codex configuration probe timed out")
        line = process.stdout.readline(MAX_LINE_BYTES + 1)
        if not line:
            raise BoundaryError("Codex configuration probe exited before responding")
        if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
            raise BoundaryError("Codex configuration probe response exceeded the safety bound")
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            # App-server may emit protocol-adjacent informational lines. Never
            # echo them because they can contain private configuration data.
            continue
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message:
            raise BoundaryError("Codex rejected the effective configuration probe")
        result = message.get("result")
        if not isinstance(result, dict):
            raise BoundaryError("Codex returned an invalid configuration response")
        return result


def _matches_required(pattern: str) -> bool:
    # Codex EnvironmentVariablePattern uses case-insensitive wildcard matching
    # for shell policy entries (for example *KEY*). Be conservative: an
    # unrecognized/odd pattern simply does not prove that the required name is
    # retained, so launch remains fail-closed.
    if not pattern or any(ord(ch) < 32 or ord(ch) == 127 for ch in pattern):
        return False
    return fnmatch.fnmatchcase(REQUIRED_ENV.casefold(), pattern.casefold())


def _validate_policy(config: dict[str, Any], ceiling: str) -> None:
    policy = config.get("shell_environment_policy")
    if not isinstance(policy, dict):
        raise BoundaryError("Codex effective shell environment policy is unavailable")

    set_values = policy.get("set")
    if not isinstance(set_values, dict) or set_values.get(REQUIRED_ENV) != ceiling:
        raise BoundaryError("Codex effective policy does not own the required Git ceiling")

    legacy_include = policy.get("include_only")
    include_patterns: list[str] = []
    if legacy_include is not None:
        if not isinstance(legacy_include, list) or not all(
            isinstance(item, str) for item in legacy_include
        ):
            raise BoundaryError("Codex effective include-only policy is invalid")
        include_patterns.extend(legacy_include)

    filters = policy.get("filters")
    if filters is not None:
        if not isinstance(filters, dict):
            raise BoundaryError("Codex effective shell environment filters are invalid")
        for pattern, action in filters.items():
            if not isinstance(pattern, str) or not isinstance(action, str):
                raise BoundaryError("Codex effective shell environment filters are invalid")
            if action.casefold() == "include":
                include_patterns.append(pattern)
            elif action.casefold() != "exclude":
                raise BoundaryError("Codex effective shell environment filter action is unknown")

    # Codex applies `set` after excludes, but applies include-only last. Thus
    # excludes cannot erase the Remote Dev-owned value; a non-empty include set
    # can. Require positive evidence that the required variable survives it.
    if include_patterns and not any(_matches_required(pattern) for pattern in include_patterns):
        raise BoundaryError("Codex effective include-only policy filters out the required Git ceiling")


def validate(binary: Path, cwd: Path, ceiling: Path) -> None:
    if not binary.is_file() or not os.access(binary, os.X_OK) or binary.is_symlink():
        raise BoundaryError("resolved Codex executable is unavailable or unsafe")
    if not cwd.is_absolute() or not cwd.is_dir():
        raise BoundaryError("Codex project directory is unavailable")
    if not ceiling.is_absolute() or not ceiling.is_dir():
        raise BoundaryError("Remote Dev workspace collection is unavailable")

    ceiling_text = str(ceiling)
    override = f"shell_environment_policy.set.{REQUIRED_ENV}={json.dumps(ceiling_text)}"
    env = os.environ.copy()
    env[REQUIRED_ENV] = ceiling_text

    process = subprocess.Popen(
        [str(binary), "app-server", "-c", override],
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
        bufsize=1,
    )
    try:
        _write_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": "remote-dev-project-boundary",
                        "title": "Remote Dev project boundary",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            },
        )
        _read_response(process, 1)
        _write_message(process, {"method": "initialized"})
        _write_message(
            process,
            {
                "id": 2,
                "method": "config/read",
                "params": {"includeLayers": False, "cwd": str(cwd)},
            },
        )
        result = _read_response(process, 2)
        config = result.get("config")
        if not isinstance(config, dict):
            raise BoundaryError("Codex did not return an effective configuration")
        _validate_policy(config, ceiling_text)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        if process.stdin is not None:
            process.stdin.close()
        if process.stdout is not None:
            process.stdout.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-binary", required=True, type=Path)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--ceiling", required=True, type=Path)
    args = parser.parse_args()

    try:
        validate(args.codex_binary, args.cwd, args.ceiling)
    except (BoundaryError, OSError, UnicodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
