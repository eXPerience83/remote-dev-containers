#!/usr/bin/env python3
"""Regression tests for the bounded Antigravity review Markdown summary."""

from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "update-antigravity-review-doc.py"
SPEC = importlib.util.spec_from_file_location("update_antigravity_review_doc", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load update-antigravity-review-doc.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

INSTALLER_SHA = "a" * 64
BINARY_SHA = "b" * 64


def reviewed() -> dict:
    return {
        "schema_version": 2,
        "inspection_date_utc": "2026-09-03",
        "workflow": {"name": "Inspect Antigravity CLI"},
        "installer": {
            "official_url": MODULE.RECONCILE.OFFICIAL_URL,
            "final_url": MODULE.RECONCILE.OFFICIAL_URL,
            "content_type": "application/x-sh",
            "size": 8123,
            "sha256": INSTALLER_SHA,
            "advertised_options": {"custom_directory": True},
            "selected_strategy": "custom-directory",
            "referenced_https_hosts": ["antigravity.google"],
        },
        "installed_binary": {
            "relative_path": MODULE.RECONCILE.EXPECTED_BINARY,
            "version": "1.2.3",
            "size": 200000000,
            "sha256": BINARY_SHA,
            "format": {},
            "dynamic_dependencies": [],
            "version_check_exit_code": 0,
            "help_check_exit_code": 0,
        },
        "filesystem": {},
        "repeat_install": {},
        "official_runtime_controls": {"disable_background_auto_update": "AGY_CLI_DISABLE_AUTO_UPDATE=true"},
        "legal_and_distribution": {"redistribution_permission_confirmed": False},
        "blocking_findings": [],
    }


class AntigravityReviewDocTests(unittest.TestCase):
    def test_render_contains_only_normalized_current_identity(self) -> None:
        output = MODULE.render(reviewed())
        self.assertIn("inspection date: **2026-09-03 UTC**", output)
        self.assertIn(INSTALLER_SHA, output)
        self.assertIn(BINARY_SHA, output)
        self.assertIn("`agy` **1.2.3**", output)
        self.assertIn("blocking findings: **none**", output)

    def test_update_preserves_human_text_outside_markers(self) -> None:
        text = (
            "# Report\n\nHuman before.\n\n"
            + MODULE.START
            + "\nold generated content\n"
            + MODULE.END
            + "\n\nHuman after.\n"
        )
        updated = MODULE.update_document(text, reviewed())
        self.assertTrue(updated.startswith("# Report\n\nHuman before."))
        self.assertTrue(updated.endswith("Human after.\n"))
        self.assertNotIn("old generated content", updated)

    def test_missing_markers_fail_closed(self) -> None:
        with self.assertRaisesRegex(MODULE.DocumentError, "exactly one managed summary block"):
            MODULE.update_document("# Report\n", reviewed())

    def test_unsafe_host_is_rejected(self) -> None:
        value = deepcopy(reviewed())
        value["installer"]["referenced_https_hosts"] = ["bad host"]
        with self.assertRaisesRegex(MODULE.DocumentError, "unsafe installer host metadata"):
            MODULE.render(value)


if __name__ == "__main__":
    unittest.main()
