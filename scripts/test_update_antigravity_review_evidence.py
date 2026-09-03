#!/usr/bin/env python3
"""Regression tests for promotion of hash-admitted Antigravity evidence."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "update-antigravity-review-evidence.py"
SPEC = importlib.util.spec_from_file_location("update_antigravity_review_evidence", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load update-antigravity-review-evidence.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

INSTALLER_SHA = "a" * 64
BINARY_SHA = "b" * 64
OLD_SHA = "c" * 64


def current() -> dict:
    return {
        "schema_version": 2,
        "workflow": {"name": "Inspect Antigravity CLI", "path": "workflow.yml"},
        "installer": {
            "official_url": "https://antigravity.google/cli/install.sh",
            "sha256": OLD_SHA,
        },
        "official_runtime_controls": {
            "disable_background_auto_update": "AGY_CLI_DISABLE_AUTO_UPDATE=true"
        },
        "legal_and_distribution": {
            "redistribution_permission_confirmed": False,
            "decision": "Do not redistribute vendor bytes.",
        },
    }


def detection() -> dict:
    return {
        "schema_version": 1,
        "kind": "antigravity-installer-detection",
        "installer": {
            "source": "https://antigravity.google/cli/install.sh",
            "final_url": "https://antigravity.google/cli/install.sh",
            "content_type": "application/x-sh",
            "size": 8000,
            "sha256": INSTALLER_SHA,
            "referenced_https_hosts": ["antigravity.google"],
        },
        "reviewed_installer_sha256": OLD_SHA,
        "changed": True,
    }


def live() -> dict:
    binary = {
        "path": ".local/bin/agy",
        "size": 200_000_000,
        "sha256": BINARY_SHA,
        "version": {"exit_code": 0, "reported_version": "1.2.3"},
        "help": {"exit_code": 0},
        "format": {
            "elf_64_bit": True,
            "x86_64": True,
            "pie": True,
            "dynamically_linked": True,
            "stripped": True,
            "interpreter": "/lib64/ld-linux-x86-64.so.2",
        },
        "dynamic_libraries": {
            "recognized": ["libc.so.6", "libm.so.6"],
            "unrecognized_count": 0,
        },
    }
    return {
        "schema_version": 2,
        "inspected_at_utc": "2026-09-03T08:30:00+00:00",
        "environment_controls": {"auto_update_disabled": True},
        "installer": {
            "source": "https://antigravity.google/cli/install.sh",
            "final_url": "https://antigravity.google/cli/install.sh",
            "content_type": "application/x-sh",
            "size": 8000,
            "sha256": INSTALLER_SHA,
            "supported_options": {
                "custom_directory": True,
                "skip_aliases": False,
                "skip_path": False,
            },
            "selected_strategy": "custom-directory",
        },
        "profiles": {"unchanged_after_second": True},
        "filesystem": {
            "after_second": [
                {"path": ".cache", "path_redacted": False, "type": "directory"},
                {"path": ".local/bin/agy", "path_redacted": False, "type": "file"},
            ]
        },
        "first_install": {"exit_code": 0},
        "second_install": {"exit_code": 0},
        "binary_after_second": binary,
        "expected_binary_present": True,
        "binary_stable_across_second_install": True,
        "installed_legal_files": [],
        "blocking_findings": [],
    }


class AntigravityEvidencePromotionTests(unittest.TestCase):
    def test_promotes_only_normalized_evidence_and_preserves_human_policy(self) -> None:
        old = current()
        result = MODULE.build_reviewed(live=live(), detection=detection(), current=old)
        self.assertEqual(result["installer"]["sha256"], INSTALLER_SHA)
        self.assertEqual(result["installed_binary"]["sha256"], BINARY_SHA)
        self.assertEqual(result["installed_binary"]["version"], "1.2.3")
        self.assertEqual(result["inspection_date_utc"], "2026-09-03")
        self.assertIs(result["legal_and_distribution"], old["legal_and_distribution"])
        self.assertIs(result["official_runtime_controls"], old["official_runtime_controls"])
        self.assertEqual(result["blocking_findings"], [])

    def test_detection_and_live_installer_must_match(self) -> None:
        bad_live = live()
        bad_live["installer"]["sha256"] = "d" * 64
        with self.assertRaisesRegex(MODULE.EvidenceError, "differs from the detected"):
            MODULE.build_reviewed(live=bad_live, detection=detection(), current=current())

    def test_unreviewed_dynamic_library_blocks_promotion(self) -> None:
        bad_live = live()
        bad_live["binary_after_second"]["dynamic_libraries"]["unrecognized_count"] = 1
        with self.assertRaisesRegex(MODULE.EvidenceError, "unreviewed dynamic"):
            MODULE.build_reviewed(live=bad_live, detection=detection(), current=current())

    def test_redacted_filesystem_path_blocks_promotion(self) -> None:
        bad_live = live()
        bad_live["filesystem"]["after_second"] = [
            {"path_sha256": "e" * 64, "path_redacted": True, "type": "file"}
        ]
        with self.assertRaisesRegex(MODULE.EvidenceError, "redacted filesystem"):
            MODULE.build_reviewed(live=bad_live, detection=detection(), current=current())

    def test_policy_fields_must_exist_in_current_reviewed_evidence(self) -> None:
        bad_current = current()
        del bad_current["legal_and_distribution"]
        with self.assertRaisesRegex(MODULE.EvidenceError, "preserved legal_and_distribution"):
            MODULE.build_reviewed(live=live(), detection=detection(), current=bad_current)


if __name__ == "__main__":
    unittest.main()
