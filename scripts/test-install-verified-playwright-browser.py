#!/usr/bin/env python3
"""Offline contract tests for the verified Chromium-only browser installer."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).with_name("install-verified-playwright-browser.py")
spec = importlib.util.spec_from_file_location("verified_playwright_browser", SCRIPT)
assert spec is not None and spec.loader is not None
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

ROOT = SCRIPT.parent.parent
MANIFEST = json.loads((ROOT / "config/playwright-browser-archives.json").read_text())


def dry_run(arch: str, root: Path) -> str:
    """Reproduce CLI dry-run metadata for an architecture without networking."""
    entries = MANIFEST["archives"][arch]
    lines = []
    for name, title in (("chromium-headless-shell", "Chrome Headless Shell"),):
        item = entries[name]
        directory = root / (name.replace("-", "_") + "-" + item["revision"])
        lines.extend([f"{title} (playwright {name} v{item['revision']})",
                      f"  Install location:    {directory}",
                      f"  Download url:        {item['url']}", ""])
    return "\n".join(lines)


def source_browser_manifest() -> dict:
    """Construct only the pinned browser metadata needed by these tests."""
    entries = MANIFEST["archives"]["amd64"]
    return {"browsers": [
        {"name": name, "revision": item["revision"],
         **({"browserVersion": item["browserVersion"]}
            if "browserVersion" in item else {})}
        for name, item in entries.items()
    ]}


class BrowserArchiveContractTests(unittest.TestCase):
    def test_both_architectures_match_exact_reviewed_metadata(self):
        for arch in ("amd64", "arm64"):
            with self.subTest(arch=arch):
                selection = installer.validate_selection(
                    MANIFEST, source_browser_manifest(),
                    MANIFEST["playwright_core_version"], arch,
                    dry_run(arch, Path("/opt/remote-dev/playwright-browsers")),
                    Path("/opt/remote-dev/playwright-browsers"))
                self.assertEqual(set(selection), set(installer.EXPECTED))
                self.assertTrue(all(len(entry["sha256"]) == 64
                                    for entry in selection.values()))

    def test_optional_ffmpeg_dry_run_is_not_installed(self):
        output = dry_run("amd64", Path("/opt/remote-dev/playwright-browsers"))
        output += ("\nFFmpeg (playwright ffmpeg v1013)\n"
                   "  Install location: /opt/remote-dev/playwright-browsers/ffmpeg-1013\n"
                   "  Download url: https://cdn.playwright.dev/ignored.zip\n")
        result = installer.validate_selection(
            MANIFEST, source_browser_manifest(),
            MANIFEST["playwright_core_version"], "amd64", output,
            Path("/opt/remote-dev/playwright-browsers"))
        self.assertEqual(set(result), {"chromium-headless-shell"})

    def test_browser_version_drift_is_blocked(self):
        with self.assertRaises(installer.InvalidBrowserArchive):
            installer.validate_selection(
                MANIFEST, source_browser_manifest(), "999.0.0", "amd64",
                dry_run("amd64", Path("/opt/remote-dev/playwright-browsers")),
                Path("/opt/remote-dev/playwright-browsers"))

    def test_download_url_mismatch_is_blocked(self):
        damaged = copy.deepcopy(MANIFEST)
        damaged["archives"]["amd64"]["chromium-headless-shell"]["url"] = "https://example.invalid/x.zip"
        with self.assertRaises(installer.InvalidBrowserArchive):
            installer.validate_selection(
                damaged, source_browser_manifest(),
                MANIFEST["playwright_core_version"], "amd64",
                dry_run("amd64", Path("/opt/remote-dev/playwright-browsers")),
                Path("/opt/remote-dev/playwright-browsers"))

    def test_sha256_validation_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "payload.zip"
            archive.write_bytes(b"known immutable bytes")
            installer.verify_sha256(archive,
                                    hashlib.sha256(archive.read_bytes()).hexdigest())
            archive.write_bytes(b"tampered")
            with self.assertRaises(installer.InvalidBrowserArchive):
                installer.verify_sha256(
                    archive, hashlib.sha256(b"known immutable bytes").hexdigest())

    def test_zip_extraction_and_marker_are_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "a.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("subdir/bin", b"executable payload")
                z.writestr("subdir/data", b"data payload")
            target = Path(tmp) / "extracted"
            installer.extract_verified_zip(archive, target, "subdir/bin")
            self.assertEqual((target / "subdir/bin").read_bytes(),
                             b"executable payload")
            self.assertEqual((target / "subdir/bin").stat().st_mode & 0o111, 0o111)
            self.assertTrue((target / "INSTALLATION_COMPLETE").is_file())

    def test_zip_path_traversal_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "a.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("../escape", "not allowed")
            with self.assertRaises(installer.InvalidBrowserArchive):
                installer.extract_verified_zip(
                    archive, Path(tmp) / "output", "escape")
            self.assertFalse((Path(tmp) / "escape").exists())

    def test_zip_symlink_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "a.zip"
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(info, "outside")
            with self.assertRaises(installer.InvalidBrowserArchive):
                installer.extract_verified_zip(
                    archive, Path(tmp) / "output", "link")


if __name__ == "__main__":
    unittest.main()
