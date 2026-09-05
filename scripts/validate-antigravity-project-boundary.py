#!/usr/bin/env python3
"""Validate the persistent Antigravity settings required by managed sessions.

This helper is intentionally read-only. Remote Dev never rewrites vendor settings
in order to satisfy a safety invariant; incompatible state blocks launch with
operator guidance instead.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
from typing import Any

MAX_SETTINGS_BYTES = 1024 * 1024
REQUIRED_UNSANDBOXED_DENY = "unsandboxed(*)"
FILE_ACTIONS = ("read_file", "write_file")


class BoundaryError(RuntimeError):
    pass


class DuplicateKeyError(ValueError):
    pass


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(key)
        result[key] = value
    return result


def _read_settings(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise BoundaryError(
            "Antigravity settings are missing; add the required managed safety policy before launch"
        ) from exc
    except OSError as exc:
        raise BoundaryError("Antigravity settings cannot be opened safely") from exc

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise BoundaryError("Antigravity settings are not a regular file")
        if info.st_uid != os.geteuid():
            raise BoundaryError("Antigravity settings have unsafe ownership")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise BoundaryError("Antigravity settings permissions are too broad")
        if info.st_size <= 0 or info.st_size > MAX_SETTINGS_BYTES:
            raise BoundaryError("Antigravity settings size is invalid")

        chunks: list[bytes] = []
        remaining = MAX_SETTINGS_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not raw or len(raw) > MAX_SETTINGS_BYTES:
            raise BoundaryError("Antigravity settings size is invalid")
    finally:
        os.close(fd)

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_object)
    except DuplicateKeyError as exc:
        raise BoundaryError("Antigravity settings contain duplicate keys") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError("Antigravity settings are not valid UTF-8 JSON") from exc
    if not isinstance(data, dict):
        raise BoundaryError("Antigravity settings root must be a JSON object")
    return data


def _inside_project(target: str, project: PurePosixPath) -> bool:
    if not target or any(ord(ch) < 32 or ord(ch) == 127 for ch in target):
        return False
    if target == "*" or target.startswith("~"):
        return False

    candidate = PurePosixPath(target)
    if candidate.is_absolute():
        try:
            candidate.relative_to(project)
        except ValueError:
            return False
        return True

    # File permission targets are documented as relative to project workspace
    # roots. Parent traversal would make that interpretation escape the selected
    # project, so it cannot be accepted for a managed session.
    return ".." not in candidate.parts


def _validate_rule_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BoundaryError(f"Antigravity permissions.{label} must be a list of strings")
    return value


def _parse_file_rule(rule: str) -> tuple[str, str] | None:
    for action in FILE_ACTIONS:
        prefix = f"{action}("
        if rule.startswith(prefix) and rule.endswith(")"):
            return action, rule[len(prefix) : -1]
    return None


def validate(settings: dict[str, Any], project: Path) -> None:
    outside = settings.get("allowNonWorkspaceAccess", False)
    if not isinstance(outside, bool):
        raise BoundaryError("allowNonWorkspaceAccess must be boolean when configured")
    if outside:
        raise BoundaryError("allowNonWorkspaceAccess must be disabled for managed Antigravity sessions")

    sandbox_setting = settings.get("enableTerminalSandbox")
    if sandbox_setting is not None and not isinstance(sandbox_setting, bool):
        raise BoundaryError("enableTerminalSandbox must be boolean when configured")

    permissions = settings.get("permissions")
    if not isinstance(permissions, dict):
        raise BoundaryError(
            "Antigravity permissions are missing; managed sessions require deny unsandboxed(*)"
        )

    allow = _validate_rule_list(permissions.get("allow"), "allow")
    deny = _validate_rule_list(permissions.get("deny"), "deny")
    _validate_rule_list(permissions.get("ask"), "ask")

    if REQUIRED_UNSANDBOXED_DENY not in deny:
        raise BoundaryError(
            "Antigravity permissions.deny must contain unsandboxed(*) for managed sessions"
        )
    if any(rule.startswith("unsandboxed(") for rule in allow):
        raise BoundaryError(
            "Antigravity permissions.allow contains an unsandboxed grant; remove it before managed launch"
        )

    project_posix = PurePosixPath(str(project))
    for rule in allow:
        parsed = _parse_file_rule(rule)
        if parsed is None:
            continue
        action, target = parsed
        if not _inside_project(target, project_posix):
            raise BoundaryError(
                f"Antigravity {action} allow rule expands filesystem access outside the selected project"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("/root/.gemini/antigravity-cli/settings.json"),
    )
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()

    if not args.project.is_absolute() or not args.project.is_dir() or args.project.is_symlink():
        print("ERROR: selected Antigravity project is unavailable or unsafe", file=sys.stderr)
        return 2

    try:
        settings = _read_settings(args.settings)
        validate(settings, args.project)
    except (BoundaryError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
