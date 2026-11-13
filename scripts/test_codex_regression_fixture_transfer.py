#!/usr/bin/env python3
"""Guard the narrow Docker archive transfer used by the Codex isolation smoke."""

from __future__ import annotations

import io
from pathlib import Path
import re
import subprocess
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SMOKE = SCRIPTS / "test-cross-service-isolation.sh"
SOURCES = (
    "test-codex-runtime-noexec-staging.py",
    "test-remote-dev-context7-runtime-isolation.py",
    "test-real-codex-project-trust.py",
)


class CodexRegressionFixtureTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.smoke = SMOKE.read_text(encoding="utf-8")
        cls.body = cls.smoke.split(
            "assert_hardened_codex_runtime_regressions() {\n", 1
        )[1].split("\n}\n", 1)[0]

    def test_one_bounded_stream_transfer_with_original_manifest(self) -> None:
        self.assertIn("require_command tar\n", self.smoke)
        self.assertIn('tar -cf - -C "$source_root/scripts" -- \\\n', self.body)
        self.assertIn('docker cp - "$codex_name:$fixture_root"', self.body)
        self.assertEqual(self.body.count("docker cp "), 1)
        self.assertNotIn("for script in", self.body)
        self.assertIn("} >/dev/null 2>&1 || copy_status=$?", self.body)
        self.assertIn('case "$copy_status" in', self.body)
        for outcome in (124, 125, 137):
            self.assertIn(f"    {outcome}) fail", self.body)

        command, _, remainder = self.body.partition("tar -cf -")
        self.assertTrue(remainder)
        filenames = tuple(
            re.findall(r"\btest-[A-Za-z0-9-]+\.py\b", remainder.split("|", 1)[0])
        )
        self.assertEqual(filenames, SOURCES)

    def test_archive_contains_only_exact_regular_source_files(self) -> None:
        completed = subprocess.run(
            ["tar", "-cf", "-", "-C", str(SCRIPTS), "--", *SOURCES],
            check=True,
            capture_output=True,
        )
        with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
            members = archive.getmembers()
            self.assertEqual(tuple(member.name for member in members), SOURCES)
            for member in members:
                with self.subTest(member=member.name):
                    self.assertTrue(member.isfile())
                    stream = archive.extractfile(member)
                    self.assertIsNotNone(stream)
                    self.assertEqual(stream.read(), (SCRIPTS / member.name).read_bytes())

    def test_all_original_regressions_and_cleanup_remain(self) -> None:
        for filename in SOURCES:
            self.assertIn(f'"$fixture_root/{filename}"', self.body)
        self.assertIn(
            'docker_exec "$codex_name" chmod a+r --', self.body
        )
        self.assertIn(
            'docker_exec "$codex_name" rm -rf -- "$fixture_root"', self.body
        )
        self.assertIn(
            'run_hardened_codex_regression "hardened Codex noexec staging regression failed"',
            self.body,
        )
        self.assertIn(
            'run_hardened_codex_regression "hardened real Codex project-trust regression failed"',
            self.body,
        )
        self.assertIn(
            'run_hardened_codex_regression "hardened Context7 runtime isolation regression failed"',
            self.body,
        )


if __name__ == "__main__":
    unittest.main()
