#!/usr/bin/env python3
"""Offline Antigravity approval-policy inspection and bounded repair.

Remote Dev owns only its launch-scoped autonomous/guarded abstraction. This
helper never executes the vendor CLI and never prints the full vendor settings.
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

SAFE_TOOL_PERMISSION = {None, "request-review"}
REPAIRABLE_TOOL_PERMISSION = {"always-proceed", "proceed-in-sandbox", "strict"}
SAFE_ARTIFACT_REVIEW = {None, "asks-for-review"}
REPAIRABLE_ARTIFACT_REVIEW = {"agent-decides", "always-proceed"}


class PolicyError(RuntimeError):
    """Unsafe or unsupported vendor policy state."""


@dataclass(frozen=True)
class SettingsSnapshot:
    path: Path
    data: dict[str, Any]
    exists: bool
    device: int | None = None
    inode: int | None = None


@dataclass(frozen=True)
class GuardedReport:
    compatible: bool
    repairable: bool
    summary: str
    conflicting_keys: tuple[str, ...]


def _validate_parent(path: Path) -> os.stat_result:
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
    return st


def load_settings(path: Path = SETTINGS_PATH) -> SettingsSnapshot:
    """Load settings without following symlinks and without exposing contents."""

    if not path.is_absolute():
        raise PolicyError("settings path must be absolute")

    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        # An absent settings file means the vendor defaults apply. The parent is
        # intentionally not required merely to report the safe default state.
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

    return SettingsSnapshot(
        path=path,
        data=data,
        exists=True,
        device=lst.st_dev,
        inode=lst.st_ino,
    )


def _classify_value(
    data: dict[str, Any],
    key: str,
    safe_values: set[str | None],
    repairable_values: set[str],
) -> tuple[str, bool, bool]:
    if key not in data:
        return "default", True, True
    value = data[key]
    if not isinstance(value, str):
        return "invalid-type", False, False
    if value in safe_values:
        return value, True, True
    if value in repairable_values:
        return value, False, True
    return "unsupported-value", False, False


def guarded_report(data: dict[str, Any]) -> GuardedReport:
    tool_label, tool_ok, tool_repairable = _classify_value(
        data,
        "toolPermission",
        SAFE_TOOL_PERMISSION,
        REPAIRABLE_TOOL_PERMISSION,
    )
    artifact_label, artifact_ok, artifact_repairable = _classify_value(
        data,
        "artifactReviewPolicy",
        SAFE_ARTIFACT_REVIEW,
        REPAIRABLE_ARTIFACT_REVIEW,
    )

    conflicts: list[str] = []
    if not tool_ok:
        conflicts.append("toolPermission")
    if not artifact_ok:
        conflicts.append("artifactReviewPolicy")

    if not conflicts:
        return GuardedReport(
            compatible=True,
            repairable=True,
            summary=(
                "OK (toolPermission="
                f"{tool_label}, artifactReviewPolicy={artifact_label})"
            ),
            conflicting_keys=(),
        )

    repairable = tool_repairable and artifact_repairable
    detail = (
        f"toolPermission={tool_label}, artifactReviewPolicy={artifact_label}"
    )
    state = "CONFLICT" if repairable else "BLOCKED"
    return GuardedReport(
        compatible=False,
        repairable=repairable,
        summary=f"{state} ({detail})",
        conflicting_keys=tuple(conflicts),
    )


def inspect_guarded(path: Path = SETTINGS_PATH) -> tuple[SettingsSnapshot, GuardedReport]:
    snapshot = load_settings(path)
    return snapshot, guarded_report(snapshot.data)


def _atomic_write_repaired(snapshot: SettingsSnapshot, data: dict[str, Any]) -> None:
    path = snapshot.path
    _validate_parent(path)
    if not snapshot.exists or snapshot.device is None or snapshot.inode is None:
        raise PolicyError("repair requires an existing settings file")

    try:
        current = os.lstat(path)
    except FileNotFoundError as exc:
        raise PolicyError("settings file disappeared before repair") from exc
    if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
        raise PolicyError("settings file changed type before repair")
    if (current.st_dev, current.st_ino) != (snapshot.device, snapshot.inode):
        raise PolicyError("settings file changed before repair")
    if current.st_uid != os.geteuid() or stat.S_IMODE(current.st_mode) & 0o077:
        raise PolicyError("settings file ownership/mode changed before repair")

    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_SETTINGS_SIZE:
        raise PolicyError("repaired settings would exceed the reviewed size limit")

    fd, temp_name = tempfile.mkstemp(prefix=".settings.remote-dev-policy.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(encoded):
            offset += os.write(fd, encoded[offset:])
        os.fsync(fd)
        os.close(fd)
        fd = -1

        latest = os.lstat(path)
        if stat.S_ISLNK(latest.st_mode) or not stat.S_ISREG(latest.st_mode):
            raise PolicyError("settings file changed type during repair")
        if (latest.st_dev, latest.st_ino) != (snapshot.device, snapshot.inode):
            raise PolicyError("settings file changed during repair")
        os.replace(temp_name, path)
        temp_name = ""

        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def repair_guarded(path: Path = SETTINGS_PATH) -> tuple[str, ...]:
    snapshot, report = inspect_guarded(path)
    if report.compatible:
        return ()
    if not report.repairable:
        raise PolicyError(
            "guarded conflict uses unsupported or malformed approval semantics; refusing automatic repair"
        )
    if not snapshot.exists:
        raise PolicyError("guarded conflict cannot be repaired because settings.json is absent")

    repaired = dict(snapshot.data)
    removed: list[str] = []
    for key in report.conflicting_keys:
        repaired.pop(key, None)
        removed.append(key)
    try:
        _atomic_write_repaired(snapshot, repaired)
    except OSError as exc:
        raise PolicyError("unable to write repaired settings safely") from exc
    return tuple(removed)


def _print_status(report: GuardedReport) -> None:
    print(f"Antigravity guarded compatibility: {report.summary}")
    if not report.compatible:
        if report.repairable:
            print(
                "Antigravity guarded repair: available via "
                "remote-dev-antigravity-policy repair-guarded --yes"
            )
        else:
            print("Antigravity guarded repair: unavailable; inspect vendor settings manually")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect/repair the minimal Antigravity approval state used by Remote Dev guarded mode."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="report guarded compatibility without modifying state")
    sub.add_parser("check-guarded", help="exit non-zero when guarded mode cannot be guaranteed")
    repair = sub.add_parser("repair-guarded", help="remove known conflicting top-level approval overrides")
    repair.add_argument("--yes", action="store_true", help="confirm the bounded settings repair")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        _, report = inspect_guarded()
        if args.command == "status":
            _print_status(report)
            return 0 if report.compatible else (3 if report.repairable else 4)
        if args.command == "check-guarded":
            _print_status(report)
            return 0 if report.compatible else (3 if report.repairable else 4)
        if args.command == "repair-guarded":
            _print_status(report)
            if report.compatible:
                print("Antigravity guarded repair: no changes required")
                return 0
            if not report.repairable:
                return 4
            if not args.yes:
                print(
                    "Refusing to modify settings without explicit --yes confirmation.",
                    file=os.sys.stderr,
                )
                return 2
            removed = repair_guarded()
            if removed:
                print("Antigravity guarded repair: removed " + ", ".join(removed))
            else:
                print("Antigravity guarded repair: no changes required")
            _, after = inspect_guarded()
            _print_status(after)
            return 0 if after.compatible else 4
    except PolicyError as exc:
        print(f"ERROR: Antigravity approval policy state is unsafe: {exc}", file=os.sys.stderr)
        return 4
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
