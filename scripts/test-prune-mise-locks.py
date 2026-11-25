#!/usr/bin/env python3
"""Offline regressions for the obsolete graph pruning boundary."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/prune-mise-locks.py"


class PruningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for filename in ("versions.env", "mise.toml", "mise.lock"):
            shutil.copyfile(ROOT / filename, self.root / filename)
        with (self.root / "mise.lock").open("rb") as handle:
            lock = tomllib.load(handle)
        self.active = []
        for name in ("pre-commit", "pytest", "ruff"):
            relative = Path(lock["tools"][f"pypi:{name}"][0]["uv"]["path"])
            shutil.copytree(ROOT / relative, self.root / relative)
            self.active.append(self.root / relative)
        original = self.active[0]
        version, suffix = original.name.split("~")
        stale_suffix = "deadbeef" if suffix != "deadbeef" else "01234567"
        self.stale = original.with_name(f"{version}~{stale_suffix}")
        shutil.copytree(original, self.stale)
        self.git("init", "-q")
        self.git("add", "-f", "--", ".")
        self.git(
            "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "commit", "-qm", "fixture",
        )

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True)

    def invoke(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(HELPER), "--root", str(self.root), *args],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return result.stdout

    def assert_active(self):
        for directory in self.active:
            self.assertTrue((directory / "uv.lock").is_file())
            self.assertTrue((directory / "pyproject.toml").is_file())

    def test_dry_run_apply_and_idempotence(self):
        self.assertIn("Would prune", self.invoke())
        self.assertTrue(self.stale.is_dir())
        self.invoke("--write")
        self.assertFalse(self.stale.exists())
        self.assert_active()
        self.assertIn("Obsolete tracked mise graphs: 0", self.invoke("--write"))
        self.git("add", "-A")
        self.assertIn("Obsolete tracked mise graphs: 0", self.invoke("--write"))

    def test_unknown_contents_fail_closed(self):
        (self.stale / "keep.txt").write_text("not generated")
        self.invoke("--write", ok=False)
        self.assertTrue((self.stale / "keep.txt").is_file())
        self.assertTrue((self.stale / "uv.lock").is_file())
        self.assert_active()

    def test_symlink_file_fail_closed(self):
        target = self.active[0] / "uv.lock"
        before = target.read_bytes()
        (self.stale / "uv.lock").unlink()
        (self.stale / "uv.lock").symlink_to(target)
        self.invoke("--write", ok=False)
        self.assertEqual(target.read_bytes(), before)
        self.assertTrue((self.stale / "uv.lock").is_symlink())

    def test_symlink_directory_fail_closed(self):
        shutil.rmtree(self.stale)
        self.stale.symlink_to(self.active[0], target_is_directory=True)
        self.invoke("--write", ok=False)
        self.assertTrue(self.stale.is_symlink())
        self.assert_active()

    def test_modified_graph_is_not_deleted(self):
        path = self.stale / "uv.lock"
        with path.open("a") as handle:
            handle.write("\n# local changes\n")
        self.invoke("--write", ok=False)
        self.assertTrue(path.is_file())

    def test_invalid_active_lock_prevents_any_deletion(self):
        with (self.active[0] / "uv.lock").open("a") as handle:
            handle.write("\n# corrupt active digest\n")
        self.invoke("--write", ok=False)
        self.assertTrue(self.stale.is_dir())


if __name__ == "__main__":
    unittest.main()
