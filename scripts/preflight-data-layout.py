#!/usr/bin/env python3
"""Fail fast unless a canonical Remote Dev host data layout already exists."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

DIRECTORY_SUFFIXES = (
    "workspaces/codex",
    "state/codex/agent",
    "state/codex/gh",
    "state/codex/git",
    "state/codex/ssh",
    "secrets/codex",
)
PASSWORD_SUFFIX = "secrets/codex/web_password.txt"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the host-side canonical data-root preflight arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every canonical Remote Dev bind source exists before "
            "Docker Compose or TrueNAS is allowed to deploy it."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Host path corresponding to REMOTE_DEV_DATA_ROOT",
    )
    return parser.parse_args(argv)


def canonical_path(path: Path) -> Path:
    """Expand a user path and make it absolute without following symlinks."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def validate_directory(path: Path, errors: list[str]) -> None:
    """Record an error unless a required host path is a real directory."""
    if path.is_symlink():
        errors.append(f"required directory must not be a symlink: {path}")
    elif not path.exists():
        errors.append(f"required directory is missing: {path}")
    elif not path.is_dir():
        errors.append(f"required directory is not a directory: {path}")


def validate_password_file(path: Path, errors: list[str]) -> None:
    """Record missing, non-regular, symlinked or overly broad password files."""
    if path.is_symlink():
        errors.append(f"password file must not be a symlink: {path}")
        return
    if not path.exists():
        errors.append(f"password file is missing: {path}")
        return
    if not path.is_file():
        errors.append(f"password path is not a regular file: {path}")
        return
    if path.stat().st_size == 0:
        errors.append(f"password file is empty: {path}")
    if os.name == "posix":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            errors.append(
                f"password file permissions are too broad: {path} "
                f"(mode {mode:04o}; expected 0600 or stricter)"
            )


def validate_layout(root: Path) -> list[str]:
    """Return every problem found in one canonical host data root."""
    errors: list[str] = []
    validate_directory(root, errors)
    for suffix in DIRECTORY_SUFFIXES:
        validate_directory(root / suffix, errors)
    validate_password_file(root / PASSWORD_SUFFIX, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    """Run the preflight and print only paths and permission metadata."""
    args = parse_args(argv)
    root = canonical_path(args.root)
    errors = validate_layout(root)
    if errors:
        print("Remote Dev data-layout preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(
            "Create or correct these host paths before deploying; Compose must "
            "not be relied upon to create them safely.",
            file=sys.stderr,
        )
        return 1

    print(f"Remote Dev data-layout preflight: OK ({root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
