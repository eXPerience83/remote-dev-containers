#!/usr/bin/env python3
"""Prepare the fixed role-private development scratch tree safely."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path


SCRATCH_ROOT = ".remote-dev-tmp"
SCRATCH_CHILDREN = ("tmp", "uv-cache", "npm-cache", "pip-cache")
PRIVATE_MODE = 0o700


class ScratchError(RuntimeError):
    pass


def open_real_directory(path: Path, *, label: str) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScratchError(f"{label} must be an existing real directory: {path}") from exc
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        os.close(descriptor)
        raise ScratchError(f"{label} must be an existing real directory: {path}")
    return descriptor


def prepare_fixed_directory(parent_fd: int, name: str, *, display_path: Path) -> int:
    try:
        os.mkdir(name, PRIVATE_MODE, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise ScratchError(f"cannot create development scratch directory: {display_path}") from exc

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ScratchError(
            f"development scratch path must be a real directory: {display_path}"
        ) from exc

    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise ScratchError(
                f"development scratch path must be a real directory: {display_path}"
            )
        if info.st_uid != os.geteuid() or info.st_gid != os.getegid():
            raise ScratchError(
                f"development scratch path has unexpected ownership: {display_path}"
            )
        os.fchmod(descriptor, PRIVATE_MODE)
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def prepare(workspace: Path) -> None:
    if not workspace.is_absolute():
        raise ScratchError("workspace must be an absolute path")

    workspace_fd = open_real_directory(workspace, label="workspace")
    root_fd: int | None = None
    try:
        root_path = workspace / SCRATCH_ROOT
        root_fd = prepare_fixed_directory(
            workspace_fd, SCRATCH_ROOT, display_path=root_path
        )
        for child in SCRATCH_CHILDREN:
            child_fd = prepare_fixed_directory(
                root_fd, child, display_path=root_path / child
            )
            os.close(child_fd)
    finally:
        if root_fd is not None:
            os.close(root_fd)
        os.close(workspace_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args(argv)
    try:
        prepare(args.workspace)
    except ScratchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
