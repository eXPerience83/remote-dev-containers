"""Read-only mount identity checks for the optional, dedicated exchange filesystem."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EXCHANGE_TARGET = "/exchange"
EXCHANGE_ENV = "REMOTE_DEV_EXCHANGE_FS"
SUPPORTED_TYPES = frozenset(("zfs", "ext4", "xfs"))
_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


@dataclass(frozen=True)
class Mount:
    device: str
    root: str
    target: str
    options: frozenset[str]
    optional: tuple[str, ...]
    fs_type: str
    source: str
    super_options: frozenset[str]

    @property
    def identity(self) -> str:
        return f"{self.fs_type}:{self.source}"


def unescape(value: str) -> str:
    return re.sub(r"\\(040|011|012|134)", lambda m: _ESCAPES[m[1]], value)


def parse_mountinfo(text: str) -> list[Mount]:
    """Parse Linux mountinfo, not /proc/mounts or st_dev alone."""
    mounts = []
    # Kernel fields use ASCII space separators and escape literal ASCII
    # whitespace. Unicode whitespace in filenames must not split a record.
    for line in text.removesuffix("\n").split("\n"):
        left, sep, right = line.partition(" - ")
        fields, tail = left.split(" "), right.split(" ")
        if (not sep or len(fields) < 6 or len(tail) != 3
                or not all(fields) or not all(tail)
                or not fields[0].isdigit() or not fields[1].isdigit()
                or not re.fullmatch(r"\d+:\d+", fields[2])):
            raise ValueError("malformed mountinfo")
        root, target = unescape(fields[3]), unescape(fields[4])
        # Pseudo-filesystems such as nsfs legitimately expose an opaque root
        # (net:[inode]) rather than an absolute path. Only the mount TARGET
        # must be absolute here. require_exchange still requires root == "/"
        # and a supported dedicated filesystem type for the actual exchange.
        if not target.startswith("/"):
            raise ValueError("invalid mountinfo target")
        if tail[0] in SUPPORTED_TYPES and not root.startswith("/"):
            raise ValueError("invalid local filesystem mount root")
        mounts.append(Mount(fields[2], root, target, frozenset(fields[5].split(",")),
                            tuple(fields[6:]), tail[0], unescape(tail[1]),
                            frozenset(tail[2].split(","))))
    if not mounts:
        raise ValueError("mountinfo is empty")
    return mounts


def read_mounts() -> list[Mount]:
    return parse_mountinfo(Path("/proc/self/mountinfo").read_bytes().decode("utf-8", "surrogateescape"))


def below(path: str, parent: str) -> bool:
    return path.startswith(parent.rstrip("/") + "/")


def exact_mount(mounts: list[Mount], target: str) -> Mount | None:
    matches = [m for m in mounts if m.target == target]
    if len(matches) > 1:
        raise ValueError("ambiguous stacked mount at exchange or data root")
    return matches[0] if matches else None


def containing_mount(mounts: list[Mount], path: str) -> Mount:
    candidates = [m for m in mounts if m.target == path or below(path, m.target)]
    if not candidates:
        raise ValueError("cannot identify containing filesystem")
    target = max((m.target for m in candidates), key=len)
    result = exact_mount(mounts, target)
    assert result is not None
    return result


def valid_identity(identity: str) -> bool:
    fs_type, sep, source = identity.partition(":")
    return bool(sep and fs_type in SUPPORTED_TYPES and source
                and not any(ord(c) < 32 or ord(c) == 127 for c in source)
                and not source.isspace())


def require_exchange(mounts: list[Mount], target: str, expected: str | None = None) -> Mount:
    """Require a distinct full local filesystem, not a subtree bind or fallback."""
    mount = exact_mount(mounts, target)
    if mount is None:
        raise ValueError("exchange is not an exact mountpoint")
    if not valid_identity(mount.identity) or mount.root != "/":
        raise ValueError("exchange requires a dedicated supported local filesystem root")
    if expected is not None and (not valid_identity(expected) or mount.identity != expected):
        raise ValueError("exchange filesystem identity does not match configured identity")
    if ("rw" not in mount.options or "ro" in mount.options
            or "rw" not in mount.super_options or "ro" in mount.super_options):
        raise ValueError("exchange filesystem is not writable")
    if any(below(m.target, target) for m in mounts):
        raise ValueError("exchange contains nested mounts")
    return mount


def verify_visible_device(target: Path, mount: Mount) -> None:
    device = target.stat(follow_symlinks=False).st_dev
    if f"{os.major(device)}:{os.minor(device)}" != mount.device:
        raise ValueError("visible exchange device differs from mount table")


def check_host(root: Path, mounts: list[Mount]) -> Mount:
    """Called after canonical layout/ancestry validation; never create anything."""
    target = root / "exchange"
    if target.is_symlink() or not target.is_dir():
        raise ValueError("exchange must already exist as a real directory")
    mount = require_exchange(mounts, str(target))
    parent = containing_mount(mounts, str(root))
    if any(m.device == mount.device and m.target != str(target) for m in mounts):
        raise ValueError("exchange filesystem has another visible mount")
    if parent.fs_type == "zfs" or mount.fs_type == "zfs":
        if (parent.target != str(root) or parent.root != "/" or parent.fs_type != "zfs"
                or mount.fs_type != "zfs" or mount.source != parent.source + "/exchange"):
            raise ValueError("TrueNAS exchange must be the direct ZFS child of the data-root dataset")
    return mount


def check_runtime(mounts: list[Mount], expected: str) -> Mount | None:
    """Return None only for the deliberately disabled configuration."""
    mount = exact_mount(mounts, EXCHANGE_TARGET)
    if not expected and mount is None:
        if any(below(m.target, EXCHANGE_TARGET) for m in mounts):
            raise ValueError("exchange has undeclared nested mounts")
        return None
    if not expected:
        raise ValueError("exchange mount is present without REMOTE_DEV_EXCHANGE_FS")
    mount = require_exchange(mounts, EXCHANGE_TARGET, expected)
    if any(field.startswith(("shared:", "master:")) for field in mount.optional):
        raise ValueError("exchange mount propagation must be private")
    if any(m.device == mount.device and m.target != EXCHANGE_TARGET for m in mounts):
        raise ValueError("exchange filesystem aliases another container mount")
    return mount


def main() -> int:
    """Immutable image invocation: no input file paths or content inspection."""
    try:
        expected = os.environ.get(EXCHANGE_ENV, "")
        if not expected:
            try:
                os.lstat(EXCHANGE_TARGET)
            except FileNotFoundError:
                # A visible mount at or below /exchange requires this entry.
                print("Exchange: OFF")
                return 0
        mount = check_runtime(read_mounts(), expected)
        if mount and (Path(EXCHANGE_TARGET).is_symlink() or not Path(EXCHANGE_TARGET).is_dir()):
            raise ValueError("exchange mount is not a real directory")
        if mount:
            verify_visible_device(Path(EXCHANGE_TARGET), mount)
    except (OSError, ValueError) as exc:
        print(f"Exchange: BLOCKED ({exc})", file=sys.stderr)
        return 1
    print("Exchange: ENABLED (verified mount; shared untrusted data)" if mount else "Exchange: OFF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
