#!/usr/bin/env python3
"""Regression tests for the Context7 reviewed npm pin updater."""

from __future__ import annotations

import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "update-context7-review.py"
SPEC = importlib.util.spec_from_file_location("update_context7_review", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load update-context7-review.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OLD_INTEGRITY = "sha512-" + base64.b64encode(b"a" * 64).decode()
NEW_INTEGRITY = "sha512-" + base64.b64encode(b"b" * 64).decode()
OTHER_INTEGRITY = "sha512-" + base64.b64encode(b"c" * 64).decode()

VERSIONS = f"""# reviewed pins
CONTEXT7_CLI_VERSION=0.5.8
CONTEXT7_CLI_SRI_SHA512={OLD_INTEGRITY}
"""
HELPER = f'''REVIEWED_CONTEXT7_CLI_VERSION = "0.5.8"
REVIEWED_CONTEXT7_CLI_INTEGRITY = (
    "{OLD_INTEGRITY}"
)
EXPECTED_PACKAGE_LICENSE = "MIT"
'''
TEST_FILE = '''def assert_reviewed_version_contract(module) -> None:
    if module.REVIEWED_CONTEXT7_CLI_VERSION != "0.5.8":
        raise AssertionError("Context7 reviewed CLI version drifted unexpectedly")
    if module.reviewed_cli_version() != "0.5.8":
        raise AssertionError("reviewed Context7 CLI version was not resolved")

# Synthetic fixture versions below are intentionally independent.
SYNTHETIC_VERSION = "0.5.8"
'''


def metadata(version: str, integrity: str = NEW_INTEGRITY) -> dict[str, object]:
    return {
        "name": "ctx7",
        "version": version,
        "license": "MIT",
        "dist": {
            "integrity": integrity,
            "tarball": f"https://registry.npmjs.org/ctx7/-/ctx7-{version}.tgz",
        },
    }


class Context7UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.versions = root / "versions.env"
        self.helper = root / "helper.py"
        self.test_file = root / "test_helper.py"
        self.metadata = root / "metadata.json"
        self.versions.write_text(VERSIONS, encoding="utf-8")
        self.helper.write_text(HELPER, encoding="utf-8")
        self.test_file.write_text(TEST_FILE, encoding="utf-8")

    def write_metadata(self, payload: dict[str, object]) -> None:
        self.metadata.write_text(json.dumps(payload), encoding="utf-8")

    def update(self, *, write: bool) -> bool:
        return MODULE.update(
            self.metadata,
            self.versions,
            self.helper,
            write=write,
            test_path=self.test_file,
        )

    def test_new_version_updates_all_reviewed_pin_sources(self) -> None:
        self.write_metadata(metadata("0.5.9"))
        changed = self.update(write=True)
        self.assertTrue(changed)
        versions_text = self.versions.read_text(encoding="utf-8")
        helper_text = self.helper.read_text(encoding="utf-8")
        test_text = self.test_file.read_text(encoding="utf-8")
        self.assertIn("CONTEXT7_CLI_VERSION=0.5.9", versions_text)
        self.assertIn(f"CONTEXT7_CLI_SRI_SHA512={NEW_INTEGRITY}", versions_text)
        self.assertIn('REVIEWED_CONTEXT7_CLI_VERSION = "0.5.9"', helper_text)
        self.assertIn(f'    "{NEW_INTEGRITY}"', helper_text)
        self.assertIn('module.REVIEWED_CONTEXT7_CLI_VERSION != "0.5.9"', test_text)
        self.assertIn('module.reviewed_cli_version() != "0.5.9"', test_text)
        self.assertIn('SYNTHETIC_VERSION = "0.5.8"', test_text)

    def test_current_version_is_idempotent(self) -> None:
        self.write_metadata(metadata("0.5.8", OLD_INTEGRITY))
        before_versions = self.versions.read_text(encoding="utf-8")
        before_helper = self.helper.read_text(encoding="utf-8")
        before_test = self.test_file.read_text(encoding="utf-8")
        changed = self.update(write=True)
        self.assertFalse(changed)
        self.assertEqual(self.versions.read_text(encoding="utf-8"), before_versions)
        self.assertEqual(self.helper.read_text(encoding="utf-8"), before_helper)
        self.assertEqual(self.test_file.read_text(encoding="utf-8"), before_test)

    def test_test_pin_drift_fails_even_without_version_change(self) -> None:
        self.write_metadata(metadata("0.5.8", OLD_INTEGRITY))
        self.test_file.write_text(TEST_FILE.replace('!= "0.5.8"', '!= "0.5.7"', 1), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.MetadataError, "tests disagree"):
            self.update(write=False)

    def test_same_version_with_changed_integrity_fails_closed(self) -> None:
        self.write_metadata(metadata("0.5.8", OTHER_INTEGRITY))
        with self.assertRaisesRegex(MODULE.MetadataError, "changed integrity"):
            self.update(write=True)

    def test_license_change_fails_closed(self) -> None:
        payload = metadata("0.5.9")
        payload["license"] = "Apache-2.0"
        self.write_metadata(payload)
        with self.assertRaisesRegex(MODULE.MetadataError, "license changed"):
            self.update(write=False)

    def test_wrong_registry_tarball_fails_closed(self) -> None:
        payload = metadata("0.5.9")
        payload["dist"] = {
            "integrity": NEW_INTEGRITY,
            "tarball": "https://registry.npmjs.org/ctx7/-/ctx7-0.5.8.tgz",
        }
        self.write_metadata(payload)
        with self.assertRaisesRegex(MODULE.MetadataError, "unexpected tarball"):
            self.update(write=False)

    def test_registry_version_regression_fails_closed(self) -> None:
        self.write_metadata(metadata("0.5.7"))
        with self.assertRaisesRegex(MODULE.MetadataError, "regressed"):
            self.update(write=False)

    def test_oversized_registry_metadata_fails_closed(self) -> None:
        self.metadata.write_bytes(b"{" + b" " * MODULE.MAX_METADATA_BYTES + b"}")
        with self.assertRaisesRegex(MODULE.MetadataError, "size is outside"):
            self.update(write=False)


if __name__ == "__main__":
    unittest.main()
