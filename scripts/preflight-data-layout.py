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


def validate_no_symlink_components(
    root: Path, paths: tuple[Path, ...], errors: list[str]
) -> None:
    """Reject symlinks at the root or at any component below the root."""
    checked: set[Path] = set()
    for path in paths:
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            errors.append(f"required path escapes the configured root: {path}")
            continue

        current = root
        for part in (None, *relative_parts):
            if part is not None:
                current /= part
            if current in checked:
                continue
            checked.add(current)
            if current.is_symlink():
                errors.append(f"persistent path component must not be a symlink: {current}")
                break


def validate_directory(path: Path, errors: list[str]) -> None:
    """Record an error unless a required host path is a real directory."""
    if not path.exists():
        errors.append(f"required directory is missing: {path}")
    elif not path.is_dir():
        errors.append(f"required directory is not a directory: {path}")


def validate_password_file(path: Path, errors: list[str]) -> None:
    """Validate the file exactly as the shell runtime will consume it."""
    if not path.exists():
        errors.append(f"password file is missing: {path}")
        return
    if not path.is_file():
        errors.append(f"password path is not a regular file: {path}")
        return

    try:
        password_bytes = path.read_bytes()
    except OSError as error:
        errors.append(f"password file cannot be read: {path} ({error})")
        return

    if not password_bytes:
        errors.append(f"password file is empty: {path}")
    else:
        # start-remote-dev-web.sh reads through shell command substitution,
        # which removes every trailing LF. Validate the resulting credential,
        # not merely the on-disk byte count.
        effective_password = password_bytes.rstrip(b"\n")
        if not effective_password:
            errors.append(
                f"password is empty after trailing newline removal: {path}"
            )
        elif b"\x00" in effective_password:
            errors.append(f"password must not contain NUL bytes: {path}")
        elif b"\n" in effective_password or b"\r" in effective_password:
            errors.append(f"password must be a single LF-terminated line: {path}")

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
    directories = tuple(root / suffix for suffix in DIRECTORY_SUFFIXES)
    password_file = root / PASSWORD_SUFFIX

    validate_no_symlink_components(root, (*directories, password_file), errors)
    validate_directory(root, errors)
    for directory in directories:
        validate_directory(directory, errors)
    validate_password_file(password_file, errors)
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
