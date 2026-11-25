#!/usr/bin/env python3
"""Offline regressions for the obsolete graph pruning boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/prune-mise-locks.py"


def fixture_environment():
    """Never inherit Git location/config overrides in disposable repositories."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return env


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
        subprocess.run(
            ["git", "-C", str(self.root), *args], check=True, env=fixture_environment()
        )

    def invoke(self, *args, ok=True, env=None):
        result = subprocess.run(
            [sys.executable, str(HELPER), "--root", str(self.root), *args],
            text=True, capture_output=True, check=False,
            env=fixture_environment() if env is None else env,
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

    def test_staged_change_hidden_by_restored_worktree(self):
        path = self.stale / "uv.lock"
        original = path.read_bytes()
        path.write_bytes(original + b"\n# staged replacement\n")
        self.git("add", "--", str(path))
        path.write_bytes(original)
        self.invoke("--write", ok=False)
        self.assertEqual(path.read_bytes(), original)

    def test_index_flags_cannot_hide_modified_bytes(self):
        path = self.stale / "uv.lock"
        original = path.read_bytes()
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", flag, "--", str(path))
                path.write_bytes(original + b"\n# hidden working-tree changes\n")
                self.invoke("--write", ok=False)
                self.assertNotEqual(path.read_bytes(), original)
                self.git("update-index", "--no-assume-unchanged", "--no-skip-worktree", "--", str(path))
                path.write_bytes(original)

    def test_git_location_overrides_cannot_redirect_pruning(self):
        with tempfile.TemporaryDirectory() as other:
            foreign = Path(other) / "foreign"
            subprocess.run(
                ["git", "clone", "-q", "--", str(self.root), str(foreign)],
                check=True, env=fixture_environment(),
            )
            self.git("rm", "--cached", "-r", "--", str(self.stale))
            self.git(
                "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
                "commit", "-qm", "untrack stale pair",
            )
            overrides = {
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(self.root),
                "GIT_INDEX_FILE": str(foreign / ".git/index"),
            }
            before = (foreign / ".git/index").read_bytes()
            # Fixture commands must ignore inherited location variables too.
            with patch.dict(os.environ, overrides):
                self.git("add", "-f", "--", "versions.env")
            self.assertEqual((foreign / ".git/index").read_bytes(), before)
            env = fixture_environment()
            env.update(overrides)
            self.assertIn("Obsolete tracked mise graphs: 0", self.invoke("--write", env=env))
            self.assertTrue(self.stale.is_dir())
            self.assertEqual((foreign / ".git/index").read_bytes(), before)
            self.assert_active()

    def test_invalid_active_lock_prevents_any_deletion(self):
        with (self.active[0] / "uv.lock").open("a") as handle:
            handle.write("\n# corrupt active digest\n")
        self.invoke("--write", ok=False)
        self.assertTrue(self.stale.is_dir())


if __name__ == "__main__":
    unittest.main()
