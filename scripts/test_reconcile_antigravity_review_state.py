#!/usr/bin/env python3
"""Regression tests for safe preservation of proposed Antigravity review evidence."""

from __future__ import annotations

import importlib.util
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "reconcile-antigravity-review-state.py"
SPEC = importlib.util.spec_from_file_location("reconcile_antigravity_review_state", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load reconcile-antigravity-review-state.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

OLD_SHA = "a" * 64
NEW_SHA = "b" * 64
BINARY_SHA = "c" * 64


def reviewed(installer_sha: str, version: str = "1.1.10") -> dict:
    return {
        "schema_version": 2,
        "inspection_date_utc": "2026-08-05",
        "workflow": {"name": "Inspect Antigravity CLI", "path": ".github/workflows/inspect-antigravity-cli.yml"},
        "installer": {
            "official_url": MODULE.OFFICIAL_URL,
            "final_url": MODULE.OFFICIAL_URL,
            "content_type": "application/x-sh",
            "size": 7354,
            "sha256": installer_sha,
            "advertised_options": {"custom_directory": True, "skip_aliases": False, "skip_path": False},
            "selected_strategy": "custom-directory",
            "referenced_https_hosts": ["antigravity.google"],
        },
        "installed_binary": {
            "relative_path": ".local/bin/agy",
            "version": version,
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
        "legal_and_distribution": {"redistribution_permission_confirmed": False, "decision": "Do not redistribute."},
        "blocking_findings": [],
    }


def detection(installer_sha: str, reviewed_sha: str = OLD_SHA) -> dict:
    return {
        "schema_version": 1,
        "kind": "antigravity-installer-detection",
        "installer": {
            "source": MODULE.OFFICIAL_URL,
            "final_url": MODULE.OFFICIAL_URL,
            "content_type": "application/x-sh",
            "size": 8000,
            "sha256": installer_sha,
            "referenced_https_hosts": ["antigravity.google"],
        },
        "reviewed_installer_sha256": reviewed_sha,
        "changed": installer_sha != reviewed_sha,
    }


class ReconcileAntigravityReviewStateTests(unittest.TestCase):
    def test_changed_live_installer_keeps_baseline_review_pending(self) -> None:
        baseline = reviewed(OLD_SHA)
        selected, normalized, preserved = MODULE.reconcile(
            live_detection=detection(NEW_SHA),
            baseline_reviewed=baseline,
            proposed_reviewed=None,
        )
        self.assertIs(selected, baseline)
        self.assertFalse(preserved)
        self.assertTrue(normalized["changed"])
        self.assertEqual(normalized["reviewed_installer_sha256"], OLD_SHA)

    def test_matching_full_proposal_is_preserved_across_scheduler_rerun(self) -> None:
        baseline = reviewed(OLD_SHA)
        proposal = reviewed(NEW_SHA, "1.1.22")
        selected, normalized, preserved = MODULE.reconcile(
            live_detection=detection(NEW_SHA),
            baseline_reviewed=baseline,
            proposed_reviewed=proposal,
        )
        self.assertIs(selected, proposal)
        self.assertTrue(preserved)
        self.assertFalse(normalized["changed"])
        self.assertEqual(normalized["reviewed_installer_sha256"], NEW_SHA)

    def test_stale_proposal_is_not_preserved(self) -> None:
        baseline = reviewed(OLD_SHA)
        stale = reviewed("d" * 64, "1.1.20")
        selected, normalized, preserved = MODULE.reconcile(
            live_detection=detection(NEW_SHA),
            baseline_reviewed=baseline,
            proposed_reviewed=stale,
        )
        self.assertIs(selected, baseline)
        self.assertFalse(preserved)
        self.assertTrue(normalized["changed"])

    def test_proposal_cannot_change_human_owned_policy(self) -> None:
        baseline = reviewed(OLD_SHA)
        proposal = reviewed(NEW_SHA, "1.1.22")
        proposal["legal_and_distribution"] = deepcopy(proposal["legal_and_distribution"])
        proposal["legal_and_distribution"]["redistribution_permission_confirmed"] = True
        with self.assertRaisesRegex(MODULE.ReconcileError, "human-owned legal_and_distribution"):
            MODULE.reconcile(
                live_detection=detection(NEW_SHA),
                baseline_reviewed=baseline,
                proposed_reviewed=proposal,
            )

    def test_live_detection_must_remain_on_fixed_origin(self) -> None:
        baseline = reviewed(OLD_SHA)
        bad = detection(NEW_SHA)
        bad["installer"]["final_url"] = "https://antigravity.google/docs"
        with self.assertRaisesRegex(MODULE.ReconcileError, "fixed official installer URL"):
            MODULE.reconcile(
                live_detection=bad,
                baseline_reviewed=baseline,
                proposed_reviewed=None,
            )


if __name__ == "__main__":
    unittest.main()
