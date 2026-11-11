#!/usr/bin/env python3
"""Offline acceptance tests for Playwright's grouped upstream update contract."""
from __future__ import annotations

import copy
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts/playwright-upstream.py"
spec = importlib.util.spec_from_file_location("playwright_upstream", SRC)
assert spec is not None and spec.loader is not None
up = importlib.util.module_from_spec(spec)
spec.loader.exec_module(up)

MANIFEST = json.loads((ROOT / "config/playwright-browser-archives.json").read_text())
PKG = json.loads((ROOT / "config/playwright-package.json").read_text())
LOCK = json.loads((ROOT / "config/playwright-package-lock.json").read_text())
BASE = up.baseline_version(ROOT)
BASE_MAJOR, BASE_MINOR, BASE_PATCH = map(int, BASE.split("."))
CANDIDATE_VERSION = f"{BASE_MAJOR}.{BASE_MINOR}.{BASE_PATCH + 2}"
OTHER_CANDIDATE_VERSION = f"{BASE_MAJOR}.{BASE_MINOR}.{BASE_PATCH + 1}"


def candidate(arch: str, version: str = CANDIDATE_VERSION) -> dict:
    lock = copy.deepcopy(LOCK)
    lock["packages"][""]["dependencies"]["@playwright/mcp"] = version
    lock["packages"]["node_modules/@playwright/mcp"]["version"] = version
    lock["packages"]["node_modules/@playwright/mcp"]["resolved"] = (
        f"https://registry.npmjs.org/@playwright/mcp/-/mcp-{version}.tgz")
    package = copy.deepcopy(PKG)
    package["dependencies"]["@playwright/mcp"] = version
    return {
        "schema_version": 1, "status": "candidate", "arch": arch,
        "baseline_version": BASE, "version": version,
        "package": package, "lock": lock,
        "playwright_core_version": MANIFEST["playwright_core_version"],
        "archives": copy.deepcopy(MANIFEST["archives"][arch]),
    }


class PlaywrightUpdaterContract(unittest.TestCase):
    def test_both_candidate_architectures_are_accepted(self):
        for arch in up.ARCHES:
            with self.subTest(arch=arch):
                self.assertEqual(up.check_report(candidate(arch), arch, BASE),
                                 "candidate")
        self.assertEqual(up.reconcile(ROOT, candidate("amd64"),
                                      candidate("arm64"), write=False),
                         "candidate")

    def test_unmodified_baseline_is_never_a_candidate(self):
        x = candidate("amd64", version=BASE)
        with self.assertRaises(up.CandidateError):
            up.check_report(x, "amd64", BASE)

    def test_deferred_one_arch_does_not_modify_other_files(self):
        unchanged = {
            "schema_version": 1, "status": "deferred", "arch": "arm64",
            "baseline_version": BASE, "reason": "DownloadFailed",
        }
        with mock.patch.object(up, "baseline_version", return_value=BASE):
            self.assertEqual(up.reconcile(
                ROOT, candidate("amd64"), unchanged, write=False), "deferred")

    def test_cross_arch_npm_lock_drift_is_rejected(self):
        other = candidate("arm64")
        other["lock"]["packages"]["node_modules/playwright"]["integrity"] = (
            "sha512-" + base64.b64encode(b"X" * 64).decode())
        with self.assertRaisesRegex(up.CandidateError,
                                    "architecture reports disagree"):
            up.reconcile(ROOT, candidate("amd64"), other, write=False)

    def test_unreviewed_download_host_is_blocked(self):
        bad = candidate("amd64")
        bad["archives"]["ffmpeg"]["url"] = "https://example.invalid/ffmpeg.zip"
        with self.assertRaises(up.CandidateError):
            up.check_report(bad, "amd64", BASE)

    def test_unreviewed_browser_archive_is_blocked(self):
        bad = candidate("amd64")
        del bad["archives"]["ffmpeg"]
        with self.assertRaises(up.CandidateError):
            up.check_report(bad, "amd64", BASE)

    def test_missing_sha256_is_blocked(self):
        bad = candidate("amd64")
        bad["archives"]["chromium-headless-shell"]["sha256"] = "0"
        with self.assertRaises(up.CandidateError):
            up.check_report(bad, "amd64", BASE)

    def test_duplicated_unknown_fields_are_blocked(self):
        bad = candidate("amd64")
        bad["code"] = "print('should never run')"
        with self.assertRaises(up.CandidateError):
            up.check_report(bad, "amd64", BASE)

    def test_package_graph_changes_are_deferred(self):
        bad = candidate("amd64")
        bad["lock"]["packages"]["node_modules/extra"] = {"version": "1.0.0"}
        with self.assertRaisesRegex(ValueError, "unexpected or missing production"):
            up.check_report(bad, "amd64", BASE)

    def test_no_write_does_not_touch_files(self):
        paths = ["versions.env", "images/base/Dockerfile",
                 "config/playwright-package.json",
                 "config/playwright-package-lock.json",
                 "config/playwright-browser-archives.json"]
        before = {p: (ROOT / p).read_bytes() for p in paths}
        up.reconcile(ROOT, candidate("amd64"), candidate("arm64"), write=False)
        self.assertEqual(before, {p: (ROOT / p).read_bytes() for p in paths})

    def test_version_and_locked_source_set_update_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("versions.env", "images/base/Dockerfile"):
                dest = root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((ROOT / rel).read_bytes())
            (root / "config").mkdir(parents=True)
            self.assertEqual(up.reconcile(
                root, candidate("amd64"), candidate("arm64"), write=True),
                "updated")
            self.assertIn(f"PLAYWRIGHT_MCP_VERSION={CANDIDATE_VERSION}",
                          (root / "versions.env").read_text())
            self.assertIn(f"ARG PLAYWRIGHT_MCP_VERSION={CANDIDATE_VERSION}",
                          (root / "images/base/Dockerfile").read_text())
            self.assertEqual(
                json.loads((root / "config/playwright-package-lock.json").read_text())
                ["packages"]["node_modules/@playwright/mcp"]["version"],
                CANDIDATE_VERSION)
            a = json.loads((root / "config/playwright-browser-archives.json").read_text())
            self.assertEqual(set(a["archives"]), set(up.ARCHES))

    def test_cross_arch_chromium_version_mismatch_is_blocked(self):
        modified = candidate("arm64")
        modified["archives"]["chromium-headless-shell"]["browserVersion"] = "999.0.0.0"
        with self.assertRaisesRegex(up.CandidateError,
                                    "architecture-specific browser versions disagree"):
            up.reconcile(ROOT, candidate("amd64"), modified, write=False)

    def test_arch_release_mismatch_is_blocked(self):
        x = candidate("arm64", version=OTHER_CANDIDATE_VERSION)
        with self.assertRaises(up.CandidateError):
            up.reconcile(ROOT, candidate("amd64"), x, write=False)

    def test_reduced_report_requires_exact_schema(self):
        report = {
            "schema_version": 1, "status": "unchanged", "arch": "amd64",
            "baseline_version": BASE, "version": BASE,
        }
        self.assertEqual(up.check_report(report, "amd64", BASE), "unchanged")
        report["fake"] = "unreviewed"
        with self.assertRaises(up.CandidateError):
            up.check_report(report, "amd64", BASE)


if __name__ == "__main__":
    unittest.main()
