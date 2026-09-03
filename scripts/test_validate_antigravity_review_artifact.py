#!/usr/bin/env python3
"""Regression tests for Antigravity metadata trust-boundary validation."""

from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "validate-antigravity-review-artifact.py"
FIXTURE = ROOT / "fixtures/antigravity-install.sh"
SPEC = importlib.util.spec_from_file_location("validate_antigravity_review_artifact", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load validate-antigravity-review-artifact.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def as_official(report: dict) -> dict:
    value = deepcopy(report)
    value["installer"]["source"] = MODULE.OFFICIAL_URL
    value["installer"]["final_url"] = MODULE.OFFICIAL_URL
    return value


class AntigravityArtifactValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture_sha = MODULE.INSPECT.sha256_file(FIXTURE)
        cls.detection = as_official(
            MODULE.DETECT.detect(
                reviewed_installer_sha256="0" * 64,
                installer_fixture=FIXTURE,
            )
        )
        cls.discovery = as_official(
            MODULE.DISCOVER.discover(
                expected_installer_sha256=fixture_sha,
                installer_fixture=FIXTURE,
            )
        )
        live = MODULE.INSPECT.inspect(FIXTURE, fixture_sha, None)
        live["installer"]["source"] = MODULE.OFFICIAL_URL
        live["installer"]["final_url"] = MODULE.OFFICIAL_URL
        live["blocking_findings"] = MODULE.INSPECT.validate_report(live)
        cls.inspection = live

    def test_detection_metadata_passes(self) -> None:
        MODULE.validate(
            self.detection,
            kind="detection",
            expected_installer=self.detection["installer"]["sha256"],
            expected_payload=None,
        )

    def test_discovery_metadata_passes(self) -> None:
        MODULE.validate(
            self.discovery,
            kind="discovery",
            expected_installer=self.discovery["installer"]["sha256"],
            expected_payload=None,
        )

    def test_full_inspection_metadata_passes(self) -> None:
        self.assertEqual(self.inspection["blocking_findings"], [])
        MODULE.validate(
            self.inspection,
            kind="inspection",
            expected_installer=self.inspection["installer"]["sha256"],
            expected_payload=self.inspection["binary_after_second"]["sha256"],
        )

    def test_raw_vendor_output_key_is_rejected_before_writer(self) -> None:
        bad = deepcopy(self.discovery)
        bad["installation"]["stdout"] = "vendor-controlled text"
        with self.assertRaisesRegex(MODULE.ArtifactError, "forbidden key"):
            MODULE.validate(
                bad,
                kind="discovery",
                expected_installer=bad["installer"]["sha256"],
                expected_payload=None,
            )

    def test_hash_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.ArtifactError, "differs from the admitted value"):
            MODULE.validate(
                self.inspection,
                kind="inspection",
                expected_installer=self.inspection["installer"]["sha256"],
                expected_payload="f" * 64,
            )


if __name__ == "__main__":
    unittest.main()
