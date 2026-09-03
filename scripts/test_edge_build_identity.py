#!/usr/bin/env python3
"""Regression tests for the dated edge build identity helper."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "format-edge-build-identity.py"
SPEC = importlib.util.spec_from_file_location("format_edge_build_identity", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load format-edge-build-identity.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EdgeBuildIdentityTests(unittest.TestCase):
    def test_formats_utc_date_and_short_source_revision(self) -> None:
        source = "d6cf2a3" + "0" * 33
        self.assertEqual(
            MODULE.format_edge_identity("2026-08-27", source),
            "edge-2026.08.27-d6cf2a3",
        )

    def test_two_revisions_on_same_date_are_distinct(self) -> None:
        first = "0123456" + "a" * 33
        second = "89abcde" + "b" * 33
        self.assertNotEqual(
            MODULE.format_edge_identity("2026-08-27", first),
            MODULE.format_edge_identity("2026-08-27", second),
        )

    def test_rejects_invalid_calendar_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "real ISO date"):
            MODULE.format_edge_identity("2026-02-30", "a" * 40)

    def test_rejects_noncanonical_source_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "40-character Git SHA"):
            MODULE.format_edge_identity("2026-08-27", "ABC123")


if __name__ == "__main__":
    unittest.main()
