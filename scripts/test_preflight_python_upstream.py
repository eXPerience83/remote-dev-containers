#!/usr/bin/env python3
"""Offline regression coverage of the bounded Python artifact lockability probe."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def load_module():
    path = Path(__file__).with_name("preflight-python-upstream.py")
    spec = importlib.util.spec_from_file_location("python_upstream_preflight", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = load_module()


def synthetic_python_lock(candidate: str, *, arm64: bool = True, provenance: bool = True) -> str:
    lines = ['lockfile_version = 3', '', '[[tools.python]]', f'version = "{candidate}"', 'backend = "core:python"', f'specifiers = ["{candidate}"]']
    for platform, arch in (
        ("linux-arm64", "aarch64"),
        ("linux-x64", "x86_64"),
    ):
        if platform == "linux-arm64" and not arm64:
            continue
        lines.extend([
            "",
            f'[tools.python."platforms.{platform}"]',
            f'checksum = "sha256:{"a" * 64}"',
            (
                'url = "https://github.com/astral-sh/python-build-standalone/'
                f'releases/download/20261010/cpython-{candidate}+20261010-'
                f'{arch}-unknown-linux-gnu-install_only_stripped.tar.gz"'
            ),
        ])
        if provenance:
            lines.append('provenance = "github-attestations"')
    return "\n".join(lines) + "\n"


class PythonPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="python-upstream-unit-")
        self.addCleanup(self.temp.cleanup)
        self.mise_bin = Path(self.temp.name) / "mise"
        self.mise_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.mise_bin.chmod(0o700)
        # Maintenance fixtures must follow reviewed pins after a later updater PR.
        pins = (Path(__file__).resolve().parents[1] / "versions.env").read_text(
            encoding="utf-8"
        )
        match314 = re.search(r"(?m)^PYTHON_VERSION=(3\.14\.[0-9]+)$", pins)
        if match314 is None:
            raise AssertionError("reviewed Python 3.14 patch pin is missing")
        self.python314 = match314.group(1)
        self.next314 = f"3.14.{int(self.python314.split('.')[2]) + 1}"
        self.previous314 = f"3.14.{int(self.python314.split('.')[2]) - 1}"
        match = re.search(r"(?m)^PYTHON_315_VERSION=(3\.15\.[0-9]+)$", pins)
        if match is None:
            raise AssertionError("reviewed Python 3.15 patch pin is missing")
        self.python315 = match.group(1)
        self.next315 = f"3.15.{int(self.python315.split('.')[2]) + 1}"

    def run_probe(self, *, output: str = "", result: int = 0, lock: str | None = None, current: str | None = None, candidate: str | None = None) -> str:
        current = self.python314 if current is None else current
        candidate = self.next314 if candidate is None else candidate
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            self.assertEqual(args[-2:], ["--platform", "linux-x64,linux-arm64"])
            self.assertEqual(args[1], "lock")
            self.assertEqual(kwargs["env"]["MISE_SAFE"], "1")
            self.assertEqual(kwargs["env"]["MISE_NOT_FOUND_AUTO_INSTALL"], "false")
            self.assertEqual(kwargs["env"]["MISE_SYSTEM_CONFIG_DIR"], str(kwargs["cwd"].parent / "system"))
            self.assertNotIn("GH_TOKEN", kwargs["env"])
            # A reviewed incumbent is deliberately present before the probe.
            # First-lock missing artifacts can be silently skipped by mise;
            # a seeded lock forces the actual platform-regression error path.
            seeded = (kwargs["cwd"] / "mise.lock").read_text(encoding="utf-8")
            self.assertIn(f'version = "{current}"', seeded)
            self.assertIn('[tools.python."platforms.linux-x64"]', seeded)
            self.assertIn('[tools.python."platforms.linux-arm64"]', seeded)
            self.assertNotIn("[[tools.node]]", seeded)
            if lock is not None:
                (kwargs["cwd"] / "mise.lock").write_text(lock, encoding="utf-8")
            return subprocess.CompletedProcess(args, result, "", output)

        with mock.patch.dict(os.environ, {"GH_TOKEN": "never-pass-this-to-mise"}):
            with mock.patch.object(probe.subprocess, "run", side_effect=fake_run):
                selected = probe.select_python_version(current, candidate, self.mise_bin)
        self.assertEqual(len(calls), 1)
        return selected

    def test_current_version_skips_resolution(self) -> None:
        with mock.patch.object(probe.subprocess, "run") as run:
            self.assertEqual(
                probe.select_python_version(self.python314, self.python314, self.mise_bin),
                self.python314,
            )
            run.assert_not_called()

    def test_both_platforms_available_selects_new_patch(self) -> None:
        self.assertEqual(
            self.run_probe(lock=synthetic_python_lock(self.next314)),
            self.next314,
        )

    def test_python_315_maintenance_can_be_admitted_without_moving_default(self) -> None:
        self.assertEqual(
            self.run_probe(
                current=self.python315,
                candidate=self.next315,
                lock=synthetic_python_lock(self.next315),
            ),
            self.next315,
        )

    def test_both_platforms_missing_defers_candidate(self) -> None:
        error = (
            f"ERROR failed to resolve python@{self.next314} for linux-arm64; refusing to replace locked versions\n"
            f"ERROR failed to resolve python@{self.next314} for linux-x64; refusing to replace locked versions\n"
        )
        self.assertEqual(self.run_probe(result=1, output=error), self.python314)

    def test_only_one_platform_missing_defers_candidate(self) -> None:
        error = f"ERROR failed to resolve python@{self.next314} for linux-arm64\n"
        self.assertEqual(self.run_probe(result=1, output=error), self.python314)

    def test_candidate_becomes_lockable_on_next_run(self) -> None:
        self.assertEqual(
            self.run_probe(result=1, output=f"ERROR failed to resolve python@{self.next314} for linux-x64"),
            self.python314,
        )
        self.assertEqual(
            self.run_probe(lock=synthetic_python_lock(self.next314)),
            self.next314,
        )

    def test_unrelated_tool_failure_is_fatal(self) -> None:
        error = (
            f"ERROR failed to resolve python@{self.next314} for linux-arm64\n"
            "ERROR failed to resolve uv@0.13.0 for linux-x64\n"
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected Python upstream resolver"):
            self.run_probe(result=1, output=error)

    def test_network_error_is_fatal(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unexpected Python upstream resolver"):
            self.run_probe(result=1, output="ERROR connection timed out")

    def test_bad_policy_output_fails_closed(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_probe(lock=synthetic_python_lock(self.next314, provenance=False))

    def test_missing_platform_fails_closed(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_probe(lock=synthetic_python_lock(self.next314, arm64=False))

    def test_malformed_lock_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            self.run_probe(lock="garbage = [")

    def test_invalid_or_older_candidate_is_fatal(self) -> None:
        for candidate in ("3.15.0", self.previous314, f"{self.next314}rc1", "3.14"):
            with self.subTest(candidate=candidate):
                with self.assertRaises(RuntimeError):
                    probe.select_python_version(self.python314, candidate, self.mise_bin)


if __name__ == "__main__":
    unittest.main()
