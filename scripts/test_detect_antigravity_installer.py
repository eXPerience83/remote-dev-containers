#!/usr/bin/env python3
"""Regression tests for bounded Antigravity installer detection."""

from __future__ import annotations

import importlib.util
import json
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

    def test_write_report_contains_only_normalized_metadata(self) -> None:
        reviewed = "f" * 64
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate.json"
            with mock.patch.object(
                MODULE.INSPECTOR,
                "run",
                side_effect=AssertionError("detection must not execute vendor bytes"),
            ):
                report = MODULE.write_report(
                    output,
                    reviewed_installer_sha256=reviewed,
                    installer_fixture=FIXTURE,
                )
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(persisted, report)
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("UNTRUSTED_VENDOR_OUTPUT_SHOULD_NOT_APPEAR", serialized)
            self.assertNotIn("download complete", serialized)

    def test_host_extraction_is_bounded_and_normalized(self) -> None:
        data = (
            b"https://Example.COM/path\n"
            b"https://example.com/other\n"
            b"https://sub.example.org:443/path\n"
        )
        self.assertEqual(
            MODULE.referenced_https_hosts(data),
            ["example.com", "sub.example.org"],
        )


if __name__ == "__main__":
    unittest.main()
