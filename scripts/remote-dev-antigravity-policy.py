#!/usr/bin/env python3
"""Offline Antigravity guarded-policy inspection and preset selection.

Remote Dev owns only its launch-scoped autonomous/guarded abstraction. Normal
status, Doctor, and launch checks are read-only. The explicit ``set-preset``
action changes only the small top-level vendor settings required to select a
reviewed guarded preset; fine-grained permission rules remain user-managed.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path("/root/.gemini/antigravity-cli/settings.json")
MAX_SETTINGS_SIZE = 1024 * 1024
GUARDED_PRESETS = {"request-review", "strict"}

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
    raw: bytes | None = None
    device: int | None = None
    inode: int | None = None


@dataclass(frozen=True)
class GuardedReport:
    compatible: bool
    preset: str
    summary: str


def _validate_parent(path: Path) -> None:
    """Require a private, service-owned settings directory before a write."""

    try:
        st = os.lstat(path.parent)
    except FileNotFoundError as exc:
        raise PolicyError(f"settings directory is missing: {path.parent}") from exc
    except OSError as exc:
        raise PolicyError(f"cannot inspect settings directory metadata: {path.parent}") from exc
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise PolicyError(f"settings directory is not a normal directory: {path.parent}")
    if st.st_uid != os.geteuid():
        raise PolicyError(f"settings directory is not owned by uid {os.geteuid()}: {path.parent}")
    if stat.S_IMODE(st.st_mode) & 0o022:
        raise PolicyError(f"settings directory is group/world writable: {path.parent}")


def load_settings(path: Path = SETTINGS_PATH) -> SettingsSnapshot:
    """Load settings without following symlinks or exposing their contents."""

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

            raw_bytes = bytearray()
            while len(raw_bytes) <= MAX_SETTINGS_SIZE:
                chunk = os.read(fd, min(65536, MAX_SETTINGS_SIZE + 1 - len(raw_bytes)))
                if not chunk:
                    break
                raw_bytes.extend(chunk)
            if len(raw_bytes) > MAX_SETTINGS_SIZE:
                raise PolicyError(f"settings file exceeded the reviewed limit while reading: {path}")
        except OSError as exc:
            raise PolicyError(f"cannot read settings file safely: {path}") from exc
    finally:
        os.close(fd)

    raw = bytes(raw_bytes)
    try:
        decoded = raw.decode("utf-8")
        data = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError(f"settings file is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(data, dict):
        raise PolicyError("settings JSON root must be an object")

    return SettingsSnapshot(
        path=path,
        data=data,
        exists=True,
        raw=raw,
        device=lst.st_dev,
        inode=lst.st_ino,
    )


def _classify_value(
    data: dict[str, Any],
    key: str,
    safe_values: set[str | None],
    blocked_values: set[str],
) -> tuple[str, bool]:
    """Return a sanitized label and whether one reviewed field is guarded-safe."""

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

    if "toolPermission" not in data:
        preset = "request-review (vendor default)"
    elif data.get("toolPermission") in GUARDED_PRESETS:
        preset = str(data["toolPermission"])
    else:
        preset = "incompatible"

    compatible = tool_ok and artifact_ok and agent_ok
    state = "OK" if compatible else "BLOCKED"
    return GuardedReport(
        compatible=compatible,
        preset=preset,
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


def _prepare_guarded_preset(data: dict[str, Any], preset: str) -> dict[str, Any]:
    """Return the minimum top-level changes needed for a managed guarded preset."""

    if preset not in GUARDED_PRESETS:
        raise PolicyError(f"unsupported guarded preset: {preset}")

    artifact = data.get("artifactReviewPolicy")
    if "artifactReviewPolicy" in data and (
        not isinstance(artifact, str)
        or artifact not in SAFE_ARTIFACT_REVIEW | BLOCKED_ARTIFACT_REVIEW
    ):
        raise PolicyError(
            "artifactReviewPolicy uses unknown or malformed semantics; refusing to overwrite it"
        )

    agent_mode = data.get("agentMode")
    if "agentMode" in data and (
        not isinstance(agent_mode, str)
        or agent_mode not in SAFE_AGENT_MODE | BLOCKED_AGENT_MODE
    ):
        raise PolicyError("agentMode uses unknown or malformed semantics; refusing to overwrite it")

    updated = dict(data)
    updated["toolPermission"] = preset
    if artifact in BLOCKED_ARTIFACT_REVIEW:
        updated["artifactReviewPolicy"] = "asks-for-review"
    if agent_mode in BLOCKED_AGENT_MODE:
        updated["agentMode"] = "default"
    return updated


def _assert_snapshot_unchanged(snapshot: SettingsSnapshot) -> None:
    """Best-effort optimistic concurrency check immediately before replacement."""

    latest = load_settings(snapshot.path)
    if snapshot.exists:
        if not latest.exists:
            raise PolicyError("settings changed before preset update; retry")
        if (latest.device, latest.inode, latest.raw) != (
            snapshot.device,
            snapshot.inode,
            snapshot.raw,
        ):
            raise PolicyError("settings changed before preset update; retry")
    elif latest.exists:
        raise PolicyError("settings appeared before preset update; retry")


def _atomic_write_settings(snapshot: SettingsSnapshot, data: dict[str, Any]) -> None:
    """Atomically replace settings after a narrow optimistic concurrency check."""

    path = snapshot.path
    _validate_parent(path)
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_SETTINGS_SIZE:
        raise PolicyError("updated settings would exceed the reviewed size limit")

    fd, temp_name = tempfile.mkstemp(prefix=".settings.remote-dev-guarded.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, encoded[offset:])
            if written <= 0:
                raise PolicyError("unable to write guarded preset safely")
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1

        _assert_snapshot_unchanged(snapshot)
        os.replace(temp_name, path)
        temp_name = ""

        dir_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            dir_flags |= os.O_DIRECTORY
        dir_fd = os.open(path.parent, dir_flags)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        raise PolicyError("unable to write guarded preset safely") from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def set_guarded_preset(preset: str, path: Path = SETTINGS_PATH) -> GuardedReport:
    """Explicitly select request-review or strict while preserving user rules."""

    snapshot = load_settings(path)
    updated = _prepare_guarded_preset(snapshot.data, preset)
    if updated != snapshot.data:
        _atomic_write_settings(snapshot, updated)
    _, report = inspect_guarded(path)
    if not report.compatible:
        raise PolicyError("guarded preset update did not produce compatible vendor settings")
    return report


def _print_status(report: GuardedReport) -> None:
    """Print only sanitized guarded state, never fine-grained rule contents."""

    print(f"Antigravity guarded compatibility: {report.summary}")
    print(f"Antigravity guarded preset: {report.preset}")
    print("Antigravity guarded policy source: settings.json")
    print("Antigravity fine-grained permissions: user-managed and preserved")


def _parser() -> argparse.ArgumentParser:
    """Build the deliberately small offline policy command interface."""

    parser = argparse.ArgumentParser(
        description="Inspect or select the reviewed Antigravity guarded permission preset."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report guarded compatibility without modifying state")
    sub.add_parser("check-guarded", help="exit non-zero when guarded mode cannot be guaranteed")
    preset = sub.add_parser(
        "set-preset",
        help="explicitly select request-review or strict for managed guarded launches",
    )
    preset.add_argument("preset", choices=sorted(GUARDED_PRESETS))
    return parser


def main() -> int:
    """Dispatch read-only diagnostics or the explicit guarded preset action."""

    args = _parser().parse_args()
    try:
        if args.command in {"status", "check-guarded"}:
            _, report = inspect_guarded()
            _print_status(report)
            return 0 if report.compatible else 4
        if args.command == "set-preset":
            report = set_guarded_preset(args.preset)
            print(f"Antigravity guarded preset updated: {args.preset}")
            _print_status(report)
            return 0
    except PolicyError as exc:
        print(f"ERROR: Antigravity approval policy state is unsafe: {exc}", file=os.sys.stderr)
        return 4
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
