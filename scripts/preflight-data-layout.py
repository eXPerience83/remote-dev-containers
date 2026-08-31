#!/usr/bin/env python3
"""Fail fast unless a canonical Remote Dev host data layout already exists."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

CODEX_DIRECTORY_SUFFIXES = (
    "workspaces/codex",
    "state/codex/agent",
    "state/codex/runtime",
    "state/codex/gh",
    "state/codex/git",
    "state/codex/ssh",
)
ANTIGRAVITY_DIRECTORY_SUFFIXES = (
    "workspaces/antigravity",
    "state/antigravity/bin",
    "state/antigravity/runtime",
    "state/antigravity/vendor",
    "state/antigravity/config",
    "state/antigravity/gh",
    "state/antigravity/git",
    "state/antigravity/ssh",
)
CODEX_SECRET_DIRECTORY_SUFFIX = "secrets/codex"
ANTIGRAVITY_SECRET_DIRECTORY_SUFFIX = "secrets/antigravity"
CODEX_PASSWORD_SUFFIX = "secrets/codex/web_password.txt"
ANTIGRAVITY_PASSWORD_SUFFIX = "secrets/antigravity/web_password.txt"
PASSWORD_SOURCES = ("environment", "file")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the host-side canonical data-root preflight arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every enabled Remote Dev bind source exists before "
            "Docker Compose or TrueNAS is allowed to deploy it."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Host path corresponding to REMOTE_DEV_DATA_ROOT",
    )
    parser.add_argument(
        "--include-antigravity",
        action="store_true",
        help="Also require the optional isolated Antigravity service layout",
    )
    parser.add_argument(
        "--password-source",
        choices=PASSWORD_SOURCES,
        default="file",
        help=(
            "Authentication source used by the deployment: environment checks "
            "only persistent workspace/state paths; file also requires and "
            "validates role-specific password files (default: file, matching "
            "compose/docker-compose.yml)"
        ),
    )
    return parser.parse_args(argv)


def canonical_path(path: Path) -> Path:
    """Expand a user path and make it absolute without following symlinks."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def validate_no_symlink_components(
    root: Path, paths: tuple[Path, ...], errors: list[str]
) -> bool:
    """Reject symlinks at the root or at any component below the root."""
    checked: set[Path] = set()
    found_symlink = False
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
                if current.is_symlink():
                    break
                continue
            checked.add(current)
            if current.is_symlink():
                errors.append(f"persistent path component must not be a symlink: {current}")
                found_symlink = True
                break
    return found_symlink


def validate_directory(path: Path, errors: list[str]) -> None:
    """Record an error unless a required host path is a real directory."""
    if not path.exists():
        errors.append(f"required directory is missing: {path}")
    elif not path.is_dir():
        errors.append(f"required directory is not a directory: {path}")


def validate_password_file(path: Path, errors: list[str]) -> None:
    """Validate one source password before deployment rematerializes it."""
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

    effective_password = (
        password_bytes[:-1] if password_bytes.endswith(b"\n") else password_bytes
    )
    if not effective_password:
        errors.append(f"password file is empty: {path}")
    elif b"\x00" in effective_password:
        errors.append(f"password must not contain NUL bytes: {path}")
    elif b"\n" in effective_password or b"\r" in effective_password:
        errors.append(f"password must contain exactly one line: {path}")

    if os.name == "posix":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            errors.append(
                f"password file permissions are too broad: {path} "
                f"(mode {mode:04o}; expected 0600 or stricter)"
            )


def validate_layout(
    root: Path, *, include_antigravity: bool, password_source: str
) -> list[str]:
    """Return every problem found for the enabled service layouts."""
    errors: list[str] = []
    suffixes = list(CODEX_DIRECTORY_SUFFIXES)
    password_files: list[Path] = []

    if include_antigravity:
        suffixes.extend(ANTIGRAVITY_DIRECTORY_SUFFIXES)

    if password_source == "file":
        suffixes.append(CODEX_SECRET_DIRECTORY_SUFFIX)
        password_files.append(root / CODEX_PASSWORD_SUFFIX)
        if include_antigravity:
            suffixes.append(ANTIGRAVITY_SECRET_DIRECTORY_SUFFIX)
            password_files.append(root / ANTIGRAVITY_PASSWORD_SUFFIX)

    directories = tuple(root / suffix for suffix in suffixes)
    password_paths = tuple(password_files)

    if validate_no_symlink_components(root, (*directories, *password_paths), errors):
        return errors

    validate_directory(root, errors)
    for directory in directories:
        validate_directory(directory, errors)
    for password_file in password_paths:
        validate_password_file(password_file, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    """Run the preflight and print only paths and permission metadata."""
    args = parse_args(argv)
    root = canonical_path(args.root)
    errors = validate_layout(
        root,
        include_antigravity=args.include_antigravity,
        password_source=args.password_source,
    )
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

    roles = "Codex + Antigravity" if args.include_antigravity else "Codex"
    print(
        f"Remote Dev data-layout preflight: OK "
        f"({root}; {roles}; passwords={args.password_source})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
