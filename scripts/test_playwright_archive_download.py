#!/usr/bin/env python3
"""Offline tests for Playwright's shared archive redirect boundary."""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("playwright_archive_download.py")
spec = importlib.util.spec_from_file_location("playwright_archive_download", SCRIPT)
assert spec is not None and spec.loader is not None
dl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dl)

CDN = "https://cdn.playwright.dev/builds/cft/some-archive.zip"
GOOGLE = "https://storage.googleapis.com/chrome-for-testing-public/140/linux64/chrome.zip"
MICROSOFT = ("https://playwright.download.prss.microsoft.com/"
             "dbazure/download/playwright/builds/ffmpeg/some.zip")


class ArchiveRedirectTests(unittest.TestCase):
    def mock_requests(self, *responses):
        pending = iter(responses)

        def fake_run(command, **kwargs):
            self.assertNotIn("--location", command)
            self.assertEqual(command[:2], ["curl", "-q"])
            self.assertIn("--write-out", command)
            code, redirect = next(pending)
            if code == 200:
                path = Path(command[command.index("--output") + 1])
                path.write_bytes(b"synthetic archive only")
            return subprocess.CompletedProcess(
                command, 0, stdout=f"{code}\n{redirect}", stderr="")
        return mock.patch.object(dl.subprocess, "run", side_effect=fake_run)

    def test_direct_https_archive(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests((200, "")) as run:
            output = Path(tmp) / "a.zip"
            dl.download_archive(CDN, output, "ffmpeg")
            self.assertEqual(output.read_bytes(), b"synthetic archive only")
            self.assertEqual(run.call_count, 1)

    def test_official_cross_host_chromium_redirect(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, GOOGLE), (200, "")) as run:
            dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], GOOGLE)

    def test_official_cross_host_ffmpeg_redirect(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (307, MICROSOFT), (200, "")) as run:
            dl.download_archive(CDN, Path(tmp) / "a.zip", "ffmpeg")
            self.assertEqual(run.call_count, 2)

    def test_google_chromium_host_not_valid_for_ffmpeg(self):
        with self.assertRaises(dl.ArchiveDownloadError):
            dl.validate_archive_url(GOOGLE, "ffmpeg")

    def test_unreviewed_host_rejected_before_following(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, "https://evil.invalid/archive.zip")) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "destination"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "ffmpeg")
            self.assertEqual(run.call_count, 1)

    def test_http_and_hostname_spoofing_rejected(self):
        for bad in ("http://cdn.playwright.dev/archive.zip",
                    "https://cdn.playwright.dev.evil.invalid/x.zip",
                    "https://cdn.playwright.dev@evil.invalid/x.zip",
                    "https://storage.googleapis.com/private/x.zip",
                    "https://cdn.playwright.dev:8443/x.zip",
                    "https://cdn.playwright.dev/x.zip?token=hidden",
                    "https://cdn.playwright.dev/x.zip\nX-Injected: true"):
            with self.subTest(bad=bad), self.assertRaises(dl.ArchiveDownloadError):
                dl.validate_archive_url(bad, "chromium-headless-shell")

    def test_redirect_loop_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, CDN)) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "loop"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "ffmpeg")
            self.assertEqual(run.call_count, 1)

    def test_redirect_hops_are_bounded(self):
        redirects = tuple((302, f"https://cdn.playwright.dev/hop-{i}")
                          for i in range(dl.MAX_HOPS))
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                *redirects) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "too many"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "ffmpeg")
            self.assertEqual(run.call_count, dl.MAX_HOPS)

    def test_archive_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (200, "")), mock.patch.object(dl, "MAX_BYTES", 4):
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "oversized"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "ffmpeg")


if __name__ == "__main__":
    unittest.main()
