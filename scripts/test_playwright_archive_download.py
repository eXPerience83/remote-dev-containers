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
            self.assertIn("--globoff", command)
            self.assertEqual(command.count("--globoff"), 1)
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
            dl.download_archive(CDN, output, "chromium-headless-shell")
            self.assertEqual(output.read_bytes(), b"synthetic archive only")
            self.assertEqual(run.call_count, 1)

    def test_official_cross_host_chromium_redirect(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, GOOGLE), (200, "")) as run:
            dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-1], GOOGLE)

    def test_official_cross_host_microsoft_redirect(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (307, MICROSOFT), (200, "")) as run:
            dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 2)

    def test_removed_ffmpeg_component_is_rejected(self):
        with self.assertRaises(dl.ArchiveDownloadError):
            dl.validate_archive_url(GOOGLE, "ffmpeg")

    def test_unreviewed_host_rejected_before_following(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, "https://evil.invalid/archive.zip")) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "destination"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 1)

    def test_globbed_storage_redirect_is_rejected_before_a_second_request(self):
        # Without --globoff, curl could turn braces into multiple requests,
        # including a URL outside the approved storage prefix.
        redirect = (
            "https://storage.googleapis.com/chrome-for-testing-public/"
            "{../other-bucket,safe}/payload.zip"
        )
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (302, redirect)) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError,
                                        "unsafe redirect URL characters"):
                dl.download_archive(
                    CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 1)

    def test_dot_segment_redirect_is_rejected_before_following(self):
        for component, redirect in (
            ("chromium-headless-shell",
             "https://storage.googleapis.com/chrome-for-testing-public/"
             "../other-bucket/payload.zip"),
            ("chromium-headless-shell",
             "https://playwright.download.prss.microsoft.com/"
             "dbazure/download/playwright/../unreviewed/payload.zip"),
        ):
            with self.subTest(component=component), tempfile.TemporaryDirectory() as tmp:
                with self.mock_requests((302, redirect)) as run:
                    with self.assertRaisesRegex(dl.ArchiveDownloadError,
                                                "unreviewed archive redirect path"):
                        dl.download_archive(CDN, Path(tmp) / "a.zip", component)
                    self.assertEqual(run.call_count, 1)

    def test_percent_encoded_dot_segment_is_rejected(self):
        url = ("https://storage.googleapis.com/chrome-for-testing-public/"
               "%2e%2e/other-bucket/payload.zip")
        with self.assertRaises(dl.ArchiveDownloadError):
            dl.validate_archive_url(url, "chromium-headless-shell")

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
                dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, 1)

    def test_redirect_hops_are_bounded(self):
        redirects = tuple((302, f"https://cdn.playwright.dev/hop-{i}")
                          for i in range(dl.MAX_HOPS))
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                *redirects) as run:
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "too many"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")
            self.assertEqual(run.call_count, dl.MAX_HOPS)

    def test_archive_size_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, self.mock_requests(
                (200, "")), mock.patch.object(dl, "MAX_BYTES", 4):
            with self.assertRaisesRegex(dl.ArchiveDownloadError, "oversized"):
                dl.download_archive(CDN, Path(tmp) / "a.zip", "chromium-headless-shell")


if __name__ == "__main__":
    unittest.main()
