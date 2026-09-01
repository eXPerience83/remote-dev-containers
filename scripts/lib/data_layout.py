#!/usr/bin/env python3
"""Canonical host-side persistent data-layout contract for Remote Dev."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DirectorySpec:
    """One required persistent host directory and its initial mode."""

    suffix: str
    mode: int


CODEX_DIRECTORY_SPECS = (
    DirectorySpec("workspaces/codex", 0o755),
    DirectorySpec("state/codex/agent", 0o700),
    DirectorySpec("state/codex/runtime", 0o700),
    DirectorySpec("state/codex/gh", 0o700),
    DirectorySpec("state/codex/git", 0o700),
    DirectorySpec("state/codex/ssh", 0o700),
)

ANTIGRAVITY_DIRECTORY_SPECS = (
    DirectorySpec("workspaces/antigravity", 0o755),
    DirectorySpec("state/antigravity/bin", 0o700),
    DirectorySpec("state/antigravity/runtime", 0o700),
    DirectorySpec("state/antigravity/vendor", 0o700),
    DirectorySpec("state/antigravity/config", 0o700),
    DirectorySpec("state/antigravity/gh", 0o700),
    DirectorySpec("state/antigravity/git", 0o700),
    DirectorySpec("state/antigravity/ssh", 0o700),
)


def canonical_path(path: Path) -> Path:
    """Expand a user path and make it absolute without following symlinks."""
    return Path(os.path.abspath(os.path.expanduser(os.fspath(path))))


def directory_specs(*, include_antigravity: bool) -> tuple[DirectorySpec, ...]:
    """Return the authoritative directory specs for the enabled roles."""
    if include_antigravity:
        return CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS
    return CODEX_DIRECTORY_SPECS


def required_directories(
    root: Path, *, include_antigravity: bool
) -> tuple[Path, ...]:
    """Return every required role-private host directory below root."""
    return tuple(
        root / spec.suffix
        for spec in directory_specs(include_antigravity=include_antigravity)
    )


def validate_root_ancestry_no_symlinks(root: Path, errors: list[str]) -> bool:
    """Reject a symlink anywhere in the configured root's existing ancestry."""
    parts = root.parts
    if not parts:
        return False

    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        if current.is_symlink():
            errors.append(
                f"persistent path component must not be a symlink: {current}"
            )
            return True
    return False


def validate_no_symlink_components(
    root: Path, paths: tuple[Path, ...], errors: list[str]
) -> bool:
    """Reject symlinks in root ancestry or any existing component below it."""
    if validate_root_ancestry_no_symlinks(root, errors):
        return True

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
                continue
            checked.add(current)
            if current.is_symlink():
                errors.append(
                    f"persistent path component must not be a symlink: {current}"
                )
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
    directories = required_directories(
        root, include_antigravity=include_antigravity
    )
    if validate_no_symlink_components(root, directories, errors):
        return errors

    validate_directory(root, errors)
    for directory in directories:
        validate_directory(directory, errors)
    return errors


def initialize_layout(root: Path, *, include_antigravity: bool) -> list[Path]:
    """Create missing canonical descendants without changing existing paths."""
    root = canonical_path(root)
    errors: list[str] = []
    specs = directory_specs(include_antigravity=include_antigravity)
    directories = tuple(root / spec.suffix for spec in specs)
    if validate_no_symlink_components(root, directories, errors):
        raise ValueError("; ".join(errors))
    if not root.exists():
        raise ValueError(f"configured root must already exist: {root}")
    if not root.is_dir():
        raise ValueError(f"configured root is not a directory: {root}")

    created: list[Path] = []
    for spec in specs:
        target = root / spec.suffix
        current = root
        parts = target.relative_to(root).parts
        for index, part in enumerate(parts):
            current /= part
            if current.is_symlink():
                raise ValueError(
                    f"persistent path component must not be a symlink: {current}"
                )
            if current.exists():
                if not current.is_dir():
                    raise ValueError(
                        f"persistent path component is not a directory: {current}"
                    )
                # Existing paths are operator-owned policy. They may be ordinary
                # directories or deliberate child-dataset mountpoints, so never
                # chmod/chown/replace them here.
                continue
            mode = spec.mode if index == len(parts) - 1 else 0o755
            current.mkdir(mode=mode)
            created.append(current)

    validation_errors = validate_layout(
        root, include_antigravity=include_antigravity
    )
    if validation_errors:
        raise ValueError("; ".join(validation_errors))
    return created
