#!/usr/bin/env python3
"""Regression tests for strict bounded Antigravity network downloads."""

from __future__ import annotations

import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

import antigravity_download as MODULE


class _Headers:
    def get_content_type(self):
        return "application/octet-stream"


class _Response:
    def __init__(self, url: str, data: bytes):
        self._url = url
        self._data = data
        self.headers = _Headers()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self._url

    def read(self, limit: int):
        return self._data[:limit]


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, request, timeout):
        return self.response


class AntigravityDownloadTests(unittest.TestCase):
    def test_initial_url_is_rejected_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                urllib.request,
                "build_opener",
                side_effect=AssertionError("opener must not be built"),
            ):
                with self.assertRaisesRegex(MODULE.DownloadError, "URL violates"):
                    MODULE.download_bytes(
                        "https://example.invalid/file",
                        Path(temporary) / "file",
                        max_bytes=1024,
                        policy=lambda url: url == "https://allowed.invalid/file",
                        user_agent="test",
                    )

    def test_redirect_handler_rejects_target_before_following(self) -> None:
        handler = MODULE.PolicyRedirectHandler(
            lambda url: url == "https://allowed.invalid/file"
        )
        with self.assertRaisesRegex(MODULE.DownloadError, "redirect left"):
            handler.redirect_request(
                mock.Mock(),
                mock.Mock(),
                302,
                "Found",
                {},
                "http://169.254.169.254/latest/meta-data/",
            )

    def test_proxy_environment_is_disabled_and_final_url_revalidated(self) -> None:
        allowed = "https://allowed.invalid/file"
        response = _Response(allowed, b"payload")
        captured_handlers = []

        def fake_build_opener(*handlers):
            captured_handlers.extend(handlers)
            return _Opener(response)

        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "file"
            with mock.patch.object(urllib.request, "build_opener", side_effect=fake_build_opener):
                data, content_type, final_url = MODULE.download_bytes(
                    allowed,
                    destination,
                    max_bytes=1024,
                    policy=lambda url: url == allowed,
                    user_agent="test",
                )
        self.assertEqual(data, b"payload")
        self.assertEqual(content_type, "application/octet-stream")
        self.assertEqual(final_url, allowed)
        self.assertEqual(destination.read_bytes(), b"payload")
        proxy_handlers = [
            handler for handler in captured_handlers if isinstance(handler, urllib.request.ProxyHandler)
        ]
        self.assertEqual(len(proxy_handlers), 1)
        self.assertEqual(proxy_handlers[0].proxies, {})

    def test_download_is_bounded(self) -> None:
        allowed = "https://allowed.invalid/file"
        response = _Response(allowed, b"12345")
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                urllib.request,
                "build_opener",
                return_value=_Opener(response),
            ):
                with self.assertRaisesRegex(MODULE.DownloadError, "size boundary"):
                    MODULE.download_bytes(
                        allowed,
                        Path(temporary) / "file",
                        max_bytes=4,
                        policy=lambda url: url == allowed,
                        user_agent="test",
                    )


if __name__ == "__main__":
    unittest.main()
