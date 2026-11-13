#!/usr/bin/env python3
"""Regression tests for the shared reviewed Antigravity HTTPS origin predicate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import antigravity_official_url as origin

ROOT = Path(__file__).resolve().parent


class AntigravityOfficialUrlTests(unittest.TestCase):
    def test_valid_same_origin_urls_preserve_existing_contract(self) -> None:
        for url in (
            "https://antigravity.google/cli/install.sh",
            "https://antigravity.google/redirected/path",
            "https://antigravity.google:443/cli/install.sh",
            "https://ANTIGRAVITY.GOOGLE/cli/install.sh",
        ):
            with self.subTest(url=url):
                self.assertTrue(origin.safe_official_url(url))

    def test_reject_nonofficial_and_ambiguous_urls(self) -> None:
        for url in (
            None,
            123,
            "",
            "http://antigravity.google/cli/install.sh",
            "https://antigravity.google.evil.example/cli/install.sh",
            "https://antigravity.google@evil.example/cli/install.sh",
            "https://user@antigravity.google/cli/install.sh",
            "https://user:password@antigravity.google/cli/install.sh",
            "https://antigravity.google:444/cli/install.sh",
            "https://antigravity.google:invalid/cli/install.sh",
            "https://antigravity.google./cli/install.sh",
            "https://antigravity.google/cli/install.sh#fragment",
            "https://antigravity.google\\@evil.example/cli/install.sh",
            "https://[::1]/cli/install.sh",
        ):
            with self.subTest(url=url):
                self.assertFalse(origin.safe_official_url(url))

    def test_reject_raw_ascii_controls_and_spaces_before_urlsplit(self) -> None:
        official = "https://antigravity.google/cli/install.sh"
        # urlsplit can normalize raw leading whitespace and TAB/CR/LF within
        # an authority; all such inputs must fail before host comparison.
        for point in (*range(0x21), 0x7F):
            control = chr(point)
            for url in (
                control + official,
                "https://antigravity.goo" + control + "gle/cli/install.sh",
                "https://antigravity.google/cli/" + control + "install.sh",
            ):
                with self.subTest(codepoint=point, url=repr(url)):
                    self.assertFalse(origin.safe_official_url(url))

    def test_shared_raw_control_helper_preserves_exact_boundary(self) -> None:
        self.assertFalse(origin.has_unsafe_raw_url_characters("https://antigravity.google/%20"))
        for point in (*range(0x21), 0x7F):
            with self.subTest(codepoint=point):
                self.assertTrue(origin.has_unsafe_raw_url_characters(chr(point)))
        self.assertFalse(origin.has_unsafe_raw_url_characters("https://antigravity.google"))

    def test_percent_encoded_space_remains_allowed(self) -> None:
        self.assertTrue(
            origin.safe_official_url("https://antigravity.google/cli/%20install.sh")
        )

    def test_both_consumers_reference_the_same_validator(self) -> None:
        for filename in (
            "reconcile-antigravity-review-state.py",
            "validate-antigravity-review-artifact.py",
        ):
            with self.subTest(filename=filename):
                spec = importlib.util.spec_from_file_location(
                    "antigravity_origin_consumer", ROOT / filename
                )
                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.loader)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.assertIs(module.safe_official_url, origin.safe_official_url)
                self.assertEqual(module.OFFICIAL_HOST, origin.OFFICIAL_HOST)


if __name__ == "__main__":
    unittest.main()
