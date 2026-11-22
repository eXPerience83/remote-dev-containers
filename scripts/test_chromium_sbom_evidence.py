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
        "image_id": "sha256:" + "c" * 64,
        "executable": executable,
        "executable_sha256": "a" * 64,
        "executable_sha1": "d" * 40,
        "license_file": executable.rsplit("/", 1)[0] + "/LICENSE.headless_shell",
        "license_sha256": "b" * 64,
        "installed_notice": mod.NOTICE,
        "notice_sha256": "b" * 64,
        "notice_sha1": "e" * 40,
    }


IMAGE = "ghcr.io/experience83/remote-dev-base@sha256:" + "a" * 64
OTHER_IMAGE = "ghcr.io/experience83/remote-dev@sha256:" + "b" * 64
LOCAL_IMAGE = "remote-dev-base:local"
LOCAL_IMAGE_ID = "sha256:" + "c" * 64


def sbom(image: str = IMAGE) -> dict:
    is_local = image.endswith(":local")
    name = ("codex-" + image.split(":")[0]) if is_local else image.split("@")[0].split("/")[-1]
    digest = LOCAL_IMAGE_ID if is_local else "sha256:" + image.split("@sha256:")[-1]
    repository = ("index.docker.io/library/" if is_local else
                  "ghcr.io/experience83/") + name
    purl = ("pkg:oci/" + name + "@" + digest +
            "?arch=amd64&repository_url=" + repository.replace("/", "%2F"))
    return {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT",
            "name": image,
            "documentNamespace": "http://trivy.dev/container_image/" + image + "-fixture",
            "packages": [{"SPDXID": "SPDXRef-ContainerImage-fixture", "name": image,
                          "externalRefs": [{"referenceCategory": "PACKAGE-MANAGER",
                                            "referenceType": "purl",
                                            "referenceLocator": purl}]}],
            "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT",
                               "relatedSpdxElement": "SPDXRef-ContainerImage-fixture",
                               "relationshipType": "DESCRIBES"}]}


class ChromiumSbomContract(unittest.TestCase):
    def test_images_have_arch_specific_provenance(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                result = mod.add_package(sbom(), evidence(arch), PINNED, IMAGE)
                package = result["packages"][-1]
                entry = PINNED["archives"][arch]["chromium-headless-shell"]
                self.assertEqual(package["versionInfo"], entry["browserVersion"])
                self.assertEqual(package["checksums"][0]["checksumValue"],
                                 entry["sha256"])
                self.assertEqual(package["downloadLocation"], entry["url"])
                self.assertFalse(package["filesAnalyzed"])
                self.assertEqual(len(result["files"]), 2)
                self.assertTrue(all(f["fileName"].startswith("./") for f in result["files"]))
                self.assertEqual({f["SPDXID"] for f in result["files"]},
                                 {mod.EXEC_ID, mod.LICENSE_ID})
                # SPDX 2.3 §8.4 requires exactly one SHA1 per file.
                for file_record in result["files"]:
                    digests = [x for x in file_record["checksums"]
                               if x["algorithm"] == "SHA1"]
                    self.assertEqual(len(digests), 1)
                    self.assertEqual(len(digests[0]["checksumValue"]), 40)
                    self.assertEqual({x["algorithm"] for x in file_record["checksums"]},
                                     {"SHA1", "SHA256"})
                # SPDX 2.3 forbids CONTAINS when filesAnalyzed=False.
                # Selected digest evidence is independently document-described,
                # not asserted to be a complete Chromium package file listing.
                self.assertFalse(any(
                    rel["spdxElementId"] == mod.PACKAGE_ID and
                    rel["relationshipType"] == "CONTAINS"
                    for rel in result["relationships"]
                ))
                self.assertEqual({
                    rel["relatedSpdxElement"] for rel in result["relationships"]
                    if rel["spdxElementId"] == result["SPDXID"]
                    and rel["relationshipType"] == "DESCRIBES"
                }, {"SPDXRef-ContainerImage-fixture", mod.PACKAGE_ID,
                    mod.EXEC_ID, mod.LICENSE_ID})
                self.assertIn("not an exhaustive package file inventory",
                              package["sourceInfo"])
                self.assertIn("Trivy did not identify or vulnerability-scan Chromium",
                              result["annotations"][0]["comment"])

    def test_cross_image_spdx_substitution_rejected(self):
        with self.assertRaisesRegex(ValueError, "different scanned image"):
            mod.add_package(sbom(OTHER_IMAGE), evidence(), PINNED, IMAGE)
        wrong_primary = sbom()
        wrong_primary["packages"][0]["name"] = OTHER_IMAGE
        with self.assertRaisesRegex(ValueError, "primary container"):
            mod.add_package(wrong_primary, evidence(), PINNED, IMAGE)
        wrong_namespace = sbom()
        wrong_namespace["documentNamespace"] = "http://trivy.dev/container_image/other"
        with self.assertRaisesRegex(ValueError, "namespace"):
            mod.add_package(wrong_namespace, evidence(), PINNED, IMAGE)

    def test_oci_root_purl_disagrees_with_candidate(self):
        for original in (IMAGE, OTHER_IMAGE):
            with self.subTest(image=original):
                sb = sbom(original)
                sb["packages"][0]["externalRefs"] = (
                    copy.deepcopy(sbom(OTHER_IMAGE if original == IMAGE else IMAGE)
                                  ["packages"][0]["externalRefs"]))
                with self.assertRaisesRegex(ValueError, "PURL"):
                    mod.add_package(sb, evidence(), PINNED, original)

    def test_local_spdx_requires_exact_docker_config_digest(self):
        mod.add_package(sbom(LOCAL_IMAGE), evidence(), PINNED, LOCAL_IMAGE)
        wrong = evidence()
        wrong["image_id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(ValueError, "PURL"):
            mod.add_package(sbom(LOCAL_IMAGE), wrong, PINNED, LOCAL_IMAGE)
        wrong = evidence()
        wrong.pop("image_id")
        with self.assertRaisesRegex(ValueError, "local image config digest"):
            mod.add_package(sbom(LOCAL_IMAGE), wrong, PINNED, LOCAL_IMAGE)

    def test_spdx_absolute_path_is_rejected(self):
        built = mod.add_package(sbom(), evidence(), PINNED, IMAGE)
        for field in built["files"]:
            damaged = copy.deepcopy(built)
            record = next(f for f in damaged["files"] if f["SPDXID"] == field["SPDXID"])
            record["fileName"] = record["fileName"][1:]
            with self.assertRaisesRegex(ValueError, "relative"):
                mod.validate_supplemental_spdx(damaged)

    def test_in_image_archive_metadata_mismatch_fails(self):
        item = evidence()
        item["manifest"]["archives"]["amd64"]["chromium-headless-shell"]["sha256"] = "c"*64
        with self.assertRaisesRegex(ValueError, "manifest differs"):
            mod.add_package(sbom(), item, PINNED, IMAGE)

    def test_absent_license_or_wrong_digest_fails(self):
        item = evidence()
        item["notice_sha256"] = "c"*64
        with self.assertRaisesRegex(ValueError, "disagree"):
            mod.add_package(sbom(), item, PINNED, IMAGE)
        item = evidence()
        item["installed_notice"] = "/etc/passwd"
        with self.assertRaisesRegex(ValueError, "paths differ"):
            mod.add_package(sbom(), item, PINNED, IMAGE)

    def test_both_final_spdx_files_reject_sha1_removal(self):
        built = mod.add_package(sbom(), evidence(), PINNED, IMAGE)
        mod.validate_supplemental_spdx(built)
        for record_id in (mod.EXEC_ID, mod.LICENSE_ID):
            damaged = copy.deepcopy(built)
            record = next(x for x in damaged["files"] if x["SPDXID"] == record_id)
            record["checksums"] = [x for x in record["checksums"]
                                   if x["algorithm"] != "SHA1"]
            with self.assertRaisesRegex(ValueError, "requires one SHA1"):
                mod.validate_supplemental_spdx(damaged)

    def test_missing_or_invalid_file_sha1_fails(self):
        item = evidence()
        item.pop("executable_sha1")
        with self.assertRaisesRegex(ValueError, "SHA-1"):
            mod.add_package(sbom(), item, PINNED, IMAGE)
        item = evidence()
        item["notice_sha1"] = "bad"
        with self.assertRaisesRegex(ValueError, "SHA-1"):
            mod.add_package(sbom(), item, PINNED, IMAGE)

    def test_idempotence_requires_explicit_review(self):
        first = mod.add_package(sbom(), evidence(), PINNED, IMAGE)
        with self.assertRaisesRegex(ValueError, "already recorded"):
            mod.add_package(first, evidence(), PINNED, IMAGE)


if __name__ == "__main__":
    unittest.main()
