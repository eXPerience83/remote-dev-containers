#!/usr/bin/env python3
"""Offline tests for Chromium SPDX supplemental identity and provenance."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts/chromium-sbom-evidence.py"
spec = importlib.util.spec_from_file_location("chromium_sbom_evidence", SOURCE)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
PINNED = json.loads((ROOT / "config/playwright-browser-archives.json").read_text())


def evidence(arch: str = "amd64") -> dict:
    entry = PINNED["archives"][arch]["chromium-headless-shell"]
    executable = ("/opt/remote-dev/playwright-browsers/chromium_headless_shell-" +
                  entry["revision"] + "/" + entry["executable"])
    return {
        "arch": arch, "manifest": copy.deepcopy(PINNED),
        "executable": executable,
        "executable_sha256": "a" * 64,
        "license_file": executable.rsplit("/", 1)[0] + "/LICENSE.headless_shell",
        "license_sha256": "b" * 64,
        "installed_notice": mod.NOTICE,
        "notice_sha256": "b" * 64,
    }


def sbom() -> dict:
    return {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [{"SPDXID": "SPDXRef-Package-Existing"}],
            "relationships": []}


class ChromiumSbomContract(unittest.TestCase):
    def test_images_have_arch_specific_provenance(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                result = mod.add_package(sbom(), evidence(arch), PINNED)
                package = result["packages"][-1]
                entry = PINNED["archives"][arch]["chromium-headless-shell"]
                self.assertEqual(package["versionInfo"], entry["browserVersion"])
                self.assertEqual(package["checksums"][0]["checksumValue"],
                                 entry["sha256"])
                self.assertEqual(package["downloadLocation"], entry["url"])
                self.assertFalse(package["filesAnalyzed"])
                self.assertEqual(len(result["files"]), 2)
                self.assertEqual({f["SPDXID"] for f in result["files"]},
                                 {mod.EXEC_ID, mod.LICENSE_ID})
                self.assertEqual(result["relationships"][-1]["relatedSpdxElement"],
                                 mod.PACKAGE_ID)
                self.assertIn("Trivy did not identify or vulnerability-scan Chromium",
                              result["annotations"][0]["comment"])

    def test_in_image_archive_metadata_mismatch_fails(self):
        item = evidence()
        item["manifest"]["archives"]["amd64"]["chromium-headless-shell"]["sha256"] = "c"*64
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            mod.add_package(sbom(), item, PINNED)

    def test_absent_license_or_wrong_digest_fails(self):
        item = evidence()
        item["notice_sha256"] = "c"*64
        with self.assertRaisesRegex(ValueError, "disagree"):
            mod.add_package(sbom(), item, PINNED)
        item = evidence()
        item["installed_notice"] = "/etc/passwd"
        with self.assertRaisesRegex(ValueError, "paths differ"):
            mod.add_package(sbom(), item, PINNED)

    def test_idempotence_requires_explicit_review(self):
        first = mod.add_package(sbom(), evidence(), PINNED)
        with self.assertRaisesRegex(ValueError, "already recorded"):
            mod.add_package(first, evidence(), PINNED)


if __name__ == "__main__":
    unittest.main()
