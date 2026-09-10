#!/usr/bin/env python3
"""Offline Antigravity guarded-policy inspection.

Remote Dev owns only its launch-scoped autonomous/guarded abstraction. This
helper never executes the vendor CLI, never modifies vendor settings, and never
prints the full settings file or fine-grained permission rules.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path("/root/.gemini/antigravity-cli/settings.json")
MAX_SETTINGS_SIZE = 1024 * 1024

SAFE_TOOL_PERMISSION = {None, "request-review", "strict"}
BLOCKED_TOOL_PERMISSION = {"always-proceed", "proceed-in-sandbox"}
SAFE_ARTIFACT_REVIEW = {None, "asks-for-review"}
BLOCKED_ARTIFACT_REVIEW = {"agent-decides", "always-proceed"}
SAFE_AGENT_MODE = {None, "default", "plan"}
BLOCKED_AGENT_MODE = {"accept-edits"}


class PolicyError(RuntimeError):
    """Unsafe or unsupported vendor policy state."""


@dataclass(frozen=True)
class SettingsSnapshot:
    path: Path
    data: dict[str, Any]
    exists: bool


@dataclass(frozen=True)
class GuardedReport:
    compatible: bool
    summary: str


def load_settings(path: Path = SETTINGS_PATH) -> SettingsSnapshot:
    """Load settings without following symlinks and without exposing contents."""

    if not path.is_absolute():
        raise PolicyError("settings path must be absolute")

    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        return SettingsSnapshot(path=path, data={}, exists=False)
    except OSError as exc:
        raise PolicyError(f"cannot inspect settings file metadata: {path}") from exc

    if stat.S_ISLNK(lst.st_mode) or not stat.S_ISREG(lst.st_mode):
        raise PolicyError(f"settings file is not a normal regular file: {path}")
    if lst.st_uid != os.geteuid():
        raise PolicyError(f"settings file is not owned by uid {os.geteuid()}: {path}")
    if stat.S_IMODE(lst.st_mode) & 0o077:
        raise PolicyError(f"settings file permissions are broader than 0600: {path}")
    if lst.st_size < 0 or lst.st_size > MAX_SETTINGS_SIZE:
        raise PolicyError(f"settings file size is outside the reviewed limit: {path}")

    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise PolicyError(f"cannot open settings file safely: {path}") from exc
    try:
        try:
            fst = os.fstat(fd)
            if not stat.S_ISREG(fst.st_mode):
                raise PolicyError(f"settings file changed type during inspection: {path}")
            if (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
                raise PolicyError(f"settings file changed during inspection: {path}")
            if fst.st_uid != os.geteuid() or stat.S_IMODE(fst.st_mode) & 0o077:
                raise PolicyError(f"settings file ownership/mode changed during inspection: {path}")
            if fst.st_size < 0 or fst.st_size > MAX_SETTINGS_SIZE:
                raise PolicyError(f"settings file size changed outside the reviewed limit: {path}")

            raw = bytearray()
            while len(raw) <= MAX_SETTINGS_SIZE:
                chunk = os.read(fd, min(65536, MAX_SETTINGS_SIZE + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
            if len(raw) > MAX_SETTINGS_SIZE:
                raise PolicyError(f"settings file exceeded the reviewed limit while reading: {path}")
        except OSError as exc:
            raise PolicyError(f"cannot read settings file safely: {path}") from exc
    finally:
        os.close(fd)

    try:
        decoded = raw.decode("utf-8")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"settings file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(data, dict):
        raise PolicyError("settings JSON root must be an object")

    return SettingsSnapshot(path=path, data=data, exists=True)


def _classify_value(
    data: dict[str, Any],
    key: str,
    safe_values: set[str | None],
    blocked_values: set[str],
) -> tuple[str, bool]:
    if key not in data:
        return "default", True
    value = data[key]
    if not isinstance(value, str):
        return "invalid-type", False
    if value in safe_values:
        return value, True
    if value in blocked_values:
        return value, False
    return "unsupported-value", False


def guarded_report(data: dict[str, Any]) -> GuardedReport:
    """Classify only settings that can disable expected guarded review stops."""

    tool_label, tool_ok = _classify_value(
        data,
        "toolPermission",
        SAFE_TOOL_PERMISSION,
        BLOCKED_TOOL_PERMISSION,
    )
    artifact_label, artifact_ok = _classify_value(
        data,
        "artifactReviewPolicy",
        SAFE_ARTIFACT_REVIEW,
        BLOCKED_ARTIFACT_REVIEW,
    )
    agent_label, agent_ok = _classify_value(
        data,
        "agentMode",
        SAFE_AGENT_MODE,
        BLOCKED_AGENT_MODE,
    )
    rules_label = "present (user-managed)" if "permissions" in data else "none"

    compatible = tool_ok and artifact_ok and agent_ok
    state = "OK" if compatible else "BLOCKED"
    return GuardedReport(
        compatible=compatible,
        summary=(
            f"{state} (toolPermission={tool_label}, "
            f"artifactReviewPolicy={artifact_label}, agentMode={agent_label}, "
            f"fine-grained rules={rules_label})"
        ),
    )


def inspect_guarded(path: Path = SETTINGS_PATH) -> tuple[SettingsSnapshot, GuardedReport]:
    """Read and classify the canonical guarded settings state."""

    snapshot = load_settings(path)
    return snapshot, guarded_report(snapshot.data)


def _print_status(report: GuardedReport) -> None:
    print(f"Antigravity guarded compatibility: {report.summary}")
    print("Antigravity guarded policy source: settings.json (read-only)")
    print("Antigravity fine-grained permissions: user-managed and preserved")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the minimal Antigravity settings required for Remote Dev guarded mode."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report guarded compatibility without modifying state")
    sub.add_parser("check-guarded", help="exit non-zero when guarded mode cannot be guaranteed")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        _, report = inspect_guarded()
        if args.command in {"status", "check-guarded"}:
            _print_status(report)
            return 0 if report.compatible else 4
    except PolicyError as exc:
        print(f"ERROR: Antigravity approval policy state is unsafe: {exc}", file=os.sys.stderr)
        return 4
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
