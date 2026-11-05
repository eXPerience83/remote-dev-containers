#!/usr/bin/env python3
"""Bounded offline regressions for mise release-admission deferral policy."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def load_module():
    path = Path(__file__).with_name("admit-mise-upstream.py")
    spec = importlib.util.spec_from_file_location("mise_upstream_admission", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


admission = load_module()


class MiseAdmissionTests(unittest.TestCase):
    def test_known_url_lookup_regression_is_deferrable(self):
        output = (
            "mise ✗ python@3.14.10 · failed: No lockfile URL found for "
            "python@3.14.10 on platform linux-x64 (--locked mode)\n"
            "mise ERROR Failed to install core:python@3.14.10: "
            "No lockfile URL found for python@3.14.10 on platform linux-x64 "
            "(--locked mode)\n"
            "mise ERROR Version: 2026.11.1 linux-x64\n"
            "mise ERROR Run with --verbose\n"
        )
        self.assertTrue(admission.known_safe_mode_lookup_regression(output, "3.14.10"))

    def test_known_version_not_in_lock_is_deferrable(self):
        output = (
            "mise ✗ python@3.14.10 · failed: python@3.14.10 is not in the lockfile\n"
            "mise ERROR Failed to install core:python@3.14.10: "
            "python@3.14.10 is not in the lockfile\n"
        )
        self.assertTrue(admission.known_safe_mode_lookup_regression(output, "3.14.10"))

    def test_unrelated_install_failure_must_not_be_suppressed(self):
        output = (
            "mise ERROR Failed to install core:python@3.14.10: "
            "No lockfile URL found for python@3.14.10 on platform linux-x64 "
            "(--locked mode)\n"
            "mise ERROR checksum mismatch in download\n"
        )
        self.assertFalse(admission.known_safe_mode_lookup_regression(output, "3.14.10"))

    def test_wrong_python_is_not_deferrable(self):
        output = "mise ERROR Failed: No lockfile URL found for python@3.14.11 on platform linux-x64 (--locked mode)\n"
        self.assertFalse(admission.known_safe_mode_lookup_regression(output, "3.14.10"))

    def test_network_failure_is_not_deferrable(self):
        self.assertFalse(
            admission.known_safe_mode_lookup_regression(
                "mise ERROR HTTPS connection timed out", "3.14.10"
            )
        )

    def test_no_errors_cannot_be_deferred(self):
        self.assertFalse(
            admission.known_safe_mode_lookup_regression(
                "Lockfile ready; Python installed", "3.14.10"
            )
        )

    def test_already_pinned_skips_candidate_probe(self):
        self.assertEqual(
            admission.select_mise(
                "2026.10.25", "2026.10.25", Path("/nonexistent/mise"), "3.14.10"
            ),
            "2026.10.25",
        )


if __name__ == "__main__":
    unittest.main()
