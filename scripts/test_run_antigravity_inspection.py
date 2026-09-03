#!/usr/bin/env python3
"""Regression tests for the safe Antigravity full-inspection prefetch gate."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "run-antigravity-inspection.py"
SPEC = importlib.util.spec_from_file_location("run_antigravity_inspection", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load run-antigravity-inspection.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AntigravityInspectionGateTests(unittest.TestCase):
    def test_wrong_prefetched_installer_hash_rejects_before_inspector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / "install.sh"
            installer.write_bytes(b"installer")
            with mock.patch.object(
                MODULE.INSPECTOR,
                "inspect",
                side_effect=AssertionError("inspector must not run before installer admission"),
            ):
                with self.assertRaisesRegex(MODULE.InspectionGateError, "prefetched installer"):
                    MODULE.inspect_prefetched_installer(
                        installer=installer,
                        expected_installer_sha256="0" * 64,
                        expected_payload_sha256="1" * 64,
                        content_type="application/x-sh",
                    )

    def test_prefetched_inspection_restores_validated_network_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installer = Path(temporary) / "install.sh"
            installer.write_bytes(b"installer")
            installer_sha = MODULE.INSPECTOR.sha256_file(installer)
            sample = {
                "installer": {
                    "source": "fixture:install.sh",
                    "final_url": "fixture:install.sh",
                    "content_type": None,
                }
            }
            with mock.patch.object(MODULE.INSPECTOR, "inspect", return_value=sample), mock.patch.object(
                MODULE.INSPECTOR, "validate_report", return_value=[]
            ):
                report = MODULE.inspect_prefetched_installer(
                    installer=installer,
                    expected_installer_sha256=installer_sha,
                    expected_payload_sha256="1" * 64,
                    content_type="application/x-sh",
                )
        self.assertEqual(
            report["installer"]["source"], MODULE.INSPECTOR.OFFICIAL_INSTALLER_URL
        )
        self.assertEqual(
            report["installer"]["final_url"], MODULE.INSPECTOR.OFFICIAL_INSTALLER_URL
        )
        self.assertEqual(report["installer"]["content_type"], "application/x-sh")
        self.assertEqual(report["blocking_findings"], [])

    def test_live_gate_uses_strict_downloader_and_hashes_before_inspection(self) -> None:
        installer_data = b"installer"
        installer_sha = MODULE.INSPECTOR.sha256_bytes(installer_data)

        def fake_download(url, destination, **kwargs):
            self.assertEqual(url, MODULE.INSPECTOR.OFFICIAL_INSTALLER_URL)
            self.assertTrue(kwargs["policy"](url))
            self.assertFalse(kwargs["policy"]("https://example.invalid/install.sh"))
            destination.write_bytes(installer_data)
            return installer_data, "application/x-sh", url

        with mock.patch.object(MODULE.NETWORK, "download_bytes", side_effect=fake_download), mock.patch.object(
            MODULE,
            "inspect_prefetched_installer",
            return_value={"blocking_findings": []},
        ) as inspect_gate:
            report = MODULE.run_inspection(
                expected_installer_sha256=installer_sha,
                expected_payload_sha256="1" * 64,
            )
        self.assertEqual(report["blocking_findings"], [])
        inspect_gate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
