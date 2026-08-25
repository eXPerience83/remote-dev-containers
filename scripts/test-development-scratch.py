#!/usr/bin/env python3
"""Focused regressions for the fixed development scratch preparer."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).with_name("remote-dev-prepare-development-scratch.py")
SPEC = importlib.util.spec_from_file_location("remote_dev_development_scratch", SOURCE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load scratch preparer: {SOURCE}")
scratch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scratch)


class DevelopmentScratchTests(unittest.TestCase):
    def assert_private_tree(self, workspace: Path) -> None:
        root = workspace / scratch.SCRATCH_ROOT
        paths = (root, *(root / child for child in scratch.SCRATCH_CHILDREN))
        for path in paths:
            info = path.lstat()
            self.assertTrue(stat.S_ISDIR(info.st_mode), path)
            self.assertFalse(path.is_symlink(), path)
            self.assertEqual((info.st_uid, info.st_gid), (os.geteuid(), os.getegid()))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o700)

    def test_create_and_reuse_preserves_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            scratch.prepare(workspace)
            self.assert_private_tree(workspace)

            cache = workspace / scratch.SCRATCH_ROOT / "npm-cache"
            marker = cache / "preserved"
            marker.write_text("keep\n", encoding="utf-8")
            os.chmod(cache, 0o755)
            original_inode = cache.stat().st_ino

            scratch.prepare(workspace)
            self.assert_private_tree(workspace)
            self.assertEqual(cache.stat().st_ino, original_inode)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_workspace_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            target = parent / "target"
            target.mkdir()
            link = parent / "workspace"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(scratch.ScratchError, "existing real directory"):
                scratch.prepare(link)
            self.assertEqual(list(target.iterdir()), [])

    def test_scratch_root_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            workspace = parent / "workspace"
            target = parent / "outside"
            workspace.mkdir()
            target.mkdir()
            marker = target / "marker"
            marker.write_text("outside\n", encoding="utf-8")
            (workspace / scratch.SCRATCH_ROOT).symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(scratch.ScratchError, "real directory"):
                scratch.prepare(workspace)
            self.assertEqual(marker.read_text(encoding="utf-8"), "outside\n")
            self.assertEqual({path.name for path in target.iterdir()}, {"marker"})

    def test_child_symlink_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            workspace = parent / "workspace"
            target = parent / "outside"
            workspace.mkdir()
            target.mkdir()
            root = workspace / scratch.SCRATCH_ROOT
            root.mkdir(mode=0o700)
            (root / "tmp").symlink_to(target, target_is_directory=True)

            with self.assertRaisesRegex(scratch.ScratchError, "real directory"):
                scratch.prepare(workspace)
            self.assertEqual(list(target.iterdir()), [])

    def test_non_directory_root_and_children_are_rejected(self) -> None:
        for name in (scratch.SCRATCH_ROOT, *scratch.SCRATCH_CHILDREN):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary) / "workspace"
                workspace.mkdir()
                if name == scratch.SCRATCH_ROOT:
                    unsafe = workspace / name
                else:
                    root = workspace / scratch.SCRATCH_ROOT
                    root.mkdir(mode=0o700)
                    unsafe = root / name
                unsafe.write_text("not a directory\n", encoding="utf-8")
                with self.assertRaisesRegex(scratch.ScratchError, "real directory"):
                    scratch.prepare(workspace)
                self.assertEqual(unsafe.read_text(encoding="utf-8"), "not a directory\n")

    def test_fifo_child_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            root = workspace / scratch.SCRATCH_ROOT
            root.mkdir(mode=0o700)
            fifo = root / "tmp"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(scratch.ScratchError, "real directory"):
                scratch.prepare(workspace)
            self.assertTrue(stat.S_ISFIFO(fifo.lstat().st_mode))

    def test_unexpected_ownership_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            root = workspace / scratch.SCRATCH_ROOT
            root.mkdir(mode=0o700)
            with mock.patch.object(os, "geteuid", return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(scratch.ScratchError, "unexpected ownership"):
                    scratch.prepare(workspace)
            self.assertTrue(root.is_dir())

    @unittest.skipUnless(os.geteuid() == 0, "requires root to create foreign ownership")
    def test_unexpected_child_ownership_fails_without_touching_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / "workspace"
            workspace.mkdir()
            scratch.prepare(workspace)
            cache = workspace / scratch.SCRATCH_ROOT / "uv-cache"
            marker = cache / "preserved"
            marker.write_text("keep\n", encoding="utf-8")
            os.chown(cache, 65534, 65534)
            try:
                with self.assertRaisesRegex(scratch.ScratchError, "unexpected ownership"):
                    scratch.prepare(workspace)
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")
            finally:
                os.chown(cache, os.geteuid(), os.getegid())


if __name__ == "__main__":
    unittest.main()
