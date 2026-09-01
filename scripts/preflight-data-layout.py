#!/usr/bin/env python3
"""Fail fast unless a canonical Remote Dev host data layout already exists."""

from __future__ import annotations

import argparse
import os
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


def validate_layout(root: Path, *, include_antigravity: bool) -> list[str]:
    """Return every problem found for the enabled service layouts."""
    errors: list[str] = []
    suffixes = list(CODEX_DIRECTORY_SUFFIXES)
    if include_antigravity:
        suffixes.extend(ANTIGRAVITY_DIRECTORY_SUFFIXES)

    directories = tuple(root / suffix for suffix in suffixes)
    if validate_no_symlink_components(root, directories, errors):
        return errors

    validate_directory(root, errors)
    for directory in directories:
        validate_directory(directory, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    """Run the preflight and report only persistent path metadata."""
    args = parse_args(argv)
    root = canonical_path(args.root)
    errors = validate_layout(root, include_antigravity=args.include_antigravity)
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
    print(f"Remote Dev data-layout preflight: OK ({root}; {roles})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
