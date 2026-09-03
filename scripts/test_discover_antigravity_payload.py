#!/usr/bin/env python3
"""Regression tests for payload discovery without Antigravity binary execution."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "discover-antigravity-payload.py"
FIXTURE = ROOT / "fixtures/antigravity-install.sh"
SPEC = importlib.util.spec_from_file_location("discover_antigravity_payload", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load discover-antigravity-payload.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AntigravityPayloadDiscoveryTests(unittest.TestCase):
    def test_discovery_requires_exact_installer_hash(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "installer SHA-256 differs"):
            MODULE.discover(
                expected_installer_sha256="0" * 64,
                installer_fixture=FIXTURE,
            )

    def test_discovery_never_directly_executes_the_payload(self) -> None:
        expected = MODULE.INSPECTOR.sha256_file(FIXTURE)
        original_run = MODULE.INSPECTOR.run

        def guarded_run(command, **kwargs):
            executable = str(command[0]) if command else ""
            if executable.endswith("/agy") or executable == "agy":
                raise AssertionError("payload discovery must not execute agy")
            return original_run(command, **kwargs)

        with mock.patch.object(MODULE.INSPECTOR, "run", side_effect=guarded_run):
            report = MODULE.discover(
                expected_installer_sha256=expected,
                installer_fixture=FIXTURE,
            )
        MODULE.validate_report(report, expected_installer_sha256=expected)
        self.assertEqual(report["installer"]["sha256"], expected)
        self.assertEqual(report["payload"]["path"], ".local/bin/agy")
        self.assertRegex(report["payload"]["sha256"], r"^[0-9a-f]{64}$")
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn("UNTRUSTED_VENDOR_OUTPUT_SHOULD_NOT_APPEAR", serialized)
        self.assertNotIn("download complete", serialized)

    def test_written_report_round_trips_through_schema_validation(self) -> None:
        expected = MODULE.INSPECTOR.sha256_file(FIXTURE)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "payload.json"
            report = MODULE.write_report(
                output,
                expected_installer_sha256=expected,
                installer_fixture=FIXTURE,
            )
            persisted = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(persisted, report)
            MODULE.validate_report(persisted, expected_installer_sha256=expected)

    def test_validation_rejects_wrong_admitted_installer(self) -> None:
        expected = MODULE.INSPECTOR.sha256_file(FIXTURE)
        report = MODULE.discover(
            expected_installer_sha256=expected,
            installer_fixture=FIXTURE,
        )
        with self.assertRaisesRegex(MODULE.DiscoveryError, "differs from the admitted"):
            MODULE.validate_report(
                report,
                expected_installer_sha256="f" * 64,
            )


if __name__ == "__main__":
    unittest.main()
