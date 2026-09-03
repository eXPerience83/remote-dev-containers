#!/usr/bin/env python3
"""Regression tests for Antigravity metadata trust-boundary validation."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "validate-antigravity-review-artifact.py"
INSPECTION_FIXTURE = ROOT / "fixtures/antigravity-install.sh"
SPEC = importlib.util.spec_from_file_location("validate_antigravity_review_artifact", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load validate-antigravity-review-artifact.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PAYLOAD = b"synthetic-antigravity-payload-do-not-execute"
VERSION = "1.2.3"
PAYLOAD_URL = (
    "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
    f"{VERSION}-123456/linux-x64/cli_linux_x64.tar.gz"
)
INSTALLER_BYTES = (
    b"#!/bin/bash\n"
    b"# antigravity-cli-auto-updater-974169037036.us-central1.run.app\n"
    b"# /manifests/ sha512\n"
)


def as_official_detection(report: dict) -> dict:
    value = deepcopy(report)
    value["installer"]["source"] = MODULE.OFFICIAL_URL
    value["installer"]["final_url"] = MODULE.OFFICIAL_URL
    return value


def as_official_discovery(report: dict) -> dict:
    value = deepcopy(report)
    value["installer"]["source"] = MODULE.OFFICIAL_URL
    value["installer"]["final_url"] = MODULE.OFFICIAL_URL
    value["manifest"]["source"] = MODULE.DISCOVER.MANIFEST_URL
    value["manifest"]["final_url"] = MODULE.DISCOVER.MANIFEST_URL
    value["archive"]["source"] = value["manifest"]["payload_url"]
    value["archive"]["final_url"] = value["manifest"]["payload_url"]
    return value


class AntigravityArtifactValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        installer = root / "install.sh"
        manifest = root / "manifest.json"
        archive = root / "payload.tar.gz"
        installer.write_bytes(INSTALLER_BYTES)
        with tarfile.open(archive, "w:gz") as handle:
            member = tarfile.TarInfo("antigravity")
            member.size = len(PAYLOAD)
            member.mode = 0o755
            handle.addfile(member, io.BytesIO(PAYLOAD))
        manifest.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "url": PAYLOAD_URL,
                    "sha512": hashlib.sha512(archive.read_bytes()).hexdigest(),
                }
            ),
            encoding="utf-8",
        )
        installer_sha = hashlib.sha256(INSTALLER_BYTES).hexdigest()

        cls.detection = as_official_detection(
            MODULE.DETECT.detect(
                reviewed_installer_sha256="0" * 64,
                installer_fixture=installer,
            )
        )
        cls.discovery = as_official_discovery(
            MODULE.DISCOVER.discover(
                expected_installer_sha256=installer_sha,
                installer_fixture=installer,
                manifest_fixture=manifest,
                archive_fixture=archive,
            )
        )

        inspection_sha = MODULE.INSPECT.sha256_file(INSPECTION_FIXTURE)
        live = MODULE.INSPECT.inspect(INSPECTION_FIXTURE, inspection_sha, None)
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
        bad["archive"]["stdout"] = "vendor-controlled text"
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

    def test_excessive_nesting_is_rejected_as_invalid_metadata(self) -> None:
        root: dict[str, object] = {}
        cursor = root
        for _ in range(MODULE.MAX_NESTING_DEPTH + 2):
            child: dict[str, object] = {}
            cursor["nested"] = child
            cursor = child
        with self.assertRaisesRegex(MODULE.ArtifactError, "nesting is too deep"):
            MODULE.validate_safe_tree(root)

    def test_discovery_rejects_manifest_origin_change(self) -> None:
        bad = deepcopy(self.discovery)
        bad["manifest"]["final_url"] = "https://example.invalid/manifest.json"
        with self.assertRaisesRegex(MODULE.ArtifactError, "payload-discovery artifact is invalid"):
            MODULE.validate(
                bad,
                kind="discovery",
                expected_installer=bad["installer"]["sha256"],
                expected_payload=None,
            )


if __name__ == "__main__":
    unittest.main()
