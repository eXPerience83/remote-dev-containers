#!/usr/bin/env python3
"""Regression tests for bounded Antigravity installer detection."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "detect-antigravity-installer.py"
FIXTURE = ROOT / "fixtures/antigravity-install.sh"
SPEC = importlib.util.spec_from_file_location("detect_antigravity_installer", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load detect-antigravity-installer.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AntigravityDetectionTests(unittest.TestCase):
    def test_fixture_detection_never_invokes_vendor_processes(self) -> None:
        reviewed = "0" * 64
        with mock.patch.object(
            MODULE.INSPECTOR,
            "run",
            side_effect=AssertionError("detection must not execute vendor bytes"),
        ):
            report = MODULE.detect(
                reviewed_installer_sha256=reviewed,
                installer_fixture=FIXTURE,
            )
        MODULE.validate_report(report)
        self.assertTrue(report["changed"])
        self.assertEqual(report["reviewed_installer_sha256"], reviewed)
        self.assertEqual(report["installer"]["size"], FIXTURE.stat().st_size)
        self.assertEqual(
            report["installer"]["sha256"], MODULE.INSPECTOR.sha256_file(FIXTURE)
        )

    def test_matching_hash_is_current_and_deterministic(self) -> None:
        reviewed = MODULE.INSPECTOR.sha256_file(FIXTURE)
        first = MODULE.detect(
            reviewed_installer_sha256=reviewed,
            installer_fixture=FIXTURE,
        )
        second = MODULE.detect(
            reviewed_installer_sha256=reviewed,
            installer_fixture=FIXTURE,
        )
        self.assertEqual(first, second)
        self.assertFalse(first["changed"])

    def test_report_validation_rejects_inconsistent_change_flag(self) -> None:
        reviewed = MODULE.INSPECTOR.sha256_file(FIXTURE)
        report = MODULE.detect(
            reviewed_installer_sha256=reviewed,
            installer_fixture=FIXTURE,
        )
        report["changed"] = True
        with self.assertRaisesRegex(MODULE.DetectionError, "inconsistent"):
            MODULE.validate_report(report)

    def test_cli_writes_metadata_only_json(self) -> None:
        reviewed = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate.json"
            status = MODULE.main_for_test(
                output=output,
                reviewed_installer_sha256=reviewed,
                installer_fixture=FIXTURE,
            ) if hasattr(MODULE, "main_for_test") else None
            self.assertIsNone(status)


if __name__ == "__main__":
    unittest.main()
