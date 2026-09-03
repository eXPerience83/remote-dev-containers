#!/usr/bin/env python3
"""Regression tests for safe preservation of proposed Antigravity review state."""

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
NEW_BINARY_SHA = "e" * 64
ARCHIVE_SHA512 = "1" * 128
MANIFEST_SHA = "2" * 64
PAYLOAD_URL = (
    "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
    "1.2.3-123456/linux-x64/cli_linux_x64.tar.gz"
)


def reviewed(
    installer_sha: str,
    version: str = "1.1.10",
    payload_sha: str = BINARY_SHA,
) -> dict:
    return {
        "schema_version": 2,
        "inspection_date_utc": "2026-08-05",
        "workflow": {
            "name": "Inspect Antigravity CLI",
            "path": ".github/workflows/inspect-antigravity-cli.yml",
        },
        "installer": {
            "official_url": MODULE.OFFICIAL_URL,
            "final_url": MODULE.OFFICIAL_URL,
            "content_type": "application/x-sh",
            "size": 7354,
            "sha256": installer_sha,
            "advertised_options": {
                "custom_directory": True,
                "skip_aliases": False,
                "skip_path": False,
            },
            "selected_strategy": "custom-directory",
            "referenced_https_hosts": ["antigravity.google"],
        },
        "installed_binary": {
            "relative_path": MODULE.EXPECTED_BINARY,
            "version": version,
            "size": 200000000,
            "sha256": payload_sha,
            "format": {},
            "dynamic_dependencies": [],
            "version_check_exit_code": 0,
            "help_check_exit_code": 0,
        },
        "filesystem": {},
        "repeat_install": {},
        "official_runtime_controls": {
            "disable_background_auto_update": "AGY_CLI_DISABLE_AUTO_UPDATE=true"
        },
        "legal_and_distribution": {
            "redistribution_permission_confirmed": False,
            "decision": "Do not redistribute.",
        },
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


def discovery(installer_sha: str, payload_sha: str = BINARY_SHA) -> dict:
    return {
        "schema_version": 2,
        "kind": "antigravity-payload-discovery",
        "installer": {
            "source": MODULE.OFFICIAL_URL,
            "final_url": MODULE.OFFICIAL_URL,
            "content_type": "application/x-sh",
            "size": 8000,
            "sha256": installer_sha,
            "manifest_url": MODULE.DISCOVERY.MANIFEST_URL,
            "archive_member": MODULE.DISCOVERY.EXPECTED_ARCHIVE_MEMBER,
        },
        "manifest": {
            "source": MODULE.DISCOVERY.MANIFEST_URL,
            "final_url": MODULE.DISCOVERY.MANIFEST_URL,
            "content_type": "application/json",
            "size": 200,
            "sha256": MANIFEST_SHA,
            "version": "1.2.3",
            "payload_url": PAYLOAD_URL,
            "payload_sha512": ARCHIVE_SHA512,
        },
        "archive": {
            "source": PAYLOAD_URL,
            "final_url": PAYLOAD_URL,
            "content_type": "application/gzip",
            "size": 1000000,
            "sha512": ARCHIVE_SHA512,
            "member": MODULE.DISCOVERY.EXPECTED_ARCHIVE_MEMBER,
        },
        "payload": {
            "path": MODULE.EXPECTED_BINARY,
            "size": 200000000,
            "sha256": payload_sha,
        },
        "blocking_findings": [],
    }


class ReconcileAntigravityReviewStateTests(unittest.TestCase):
    def reconcile(
        self,
        *,
        live,
        baseline,
        live_candidate=None,
        proposal=None,
        candidate=None,
    ):
        return MODULE.reconcile(
            live_detection=live,
            baseline_reviewed=baseline,
            live_discovery=live_candidate,
            proposed_reviewed=proposal,
            proposed_discovery=candidate,
        )

    def test_changed_live_installer_without_discovery_keeps_baseline_pending(self) -> None:
        baseline = reviewed(OLD_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(NEW_SHA), baseline=baseline
        )
        self.assertIs(selected, baseline)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "baseline review + live detection")
        self.assertTrue(normalized["changed"])
        self.assertEqual(normalized["reviewed_installer_sha256"], OLD_SHA)

    def test_reviewed_installer_can_detect_new_payload_statically(self) -> None:
        baseline = reviewed(OLD_SHA)
        live_candidate = discovery(OLD_SHA, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(OLD_SHA), baseline=baseline, live_candidate=live_candidate
        )
        self.assertIs(selected, baseline)
        self.assertIs(candidate, live_candidate)
        self.assertEqual(
            disposition, "live payload change detected statically with reviewed installer"
        )
        self.assertFalse(normalized["changed"])
        self.assertEqual(candidate["payload"]["sha256"], NEW_BINARY_SHA)

    def test_changed_installer_and_payload_can_be_discovered_statically(self) -> None:
        baseline = reviewed(OLD_SHA)
        live_candidate = discovery(NEW_SHA, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(NEW_SHA), baseline=baseline, live_candidate=live_candidate
        )
        self.assertIs(selected, baseline)
        self.assertIs(candidate, live_candidate)
        self.assertEqual(disposition, "live installer/payload change detected statically")
        self.assertTrue(normalized["changed"])
        self.assertEqual(candidate["installer"]["sha256"], NEW_SHA)
        self.assertEqual(candidate["payload"]["sha256"], NEW_BINARY_SHA)

    def test_reviewed_pair_produces_no_candidate_noise(self) -> None:
        baseline = reviewed(OLD_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(OLD_SHA),
            baseline=baseline,
            live_candidate=discovery(OLD_SHA, BINARY_SHA),
        )
        self.assertIs(selected, baseline)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "baseline review + live detection")
        self.assertFalse(normalized["changed"])

    def test_live_discovery_must_match_detected_installer(self) -> None:
        baseline = reviewed(OLD_SHA)
        with self.assertRaisesRegex(MODULE.ReconcileError, "does not match"):
            self.reconcile(
                live=detection(NEW_SHA),
                baseline=baseline,
                live_candidate=discovery(OLD_SHA, NEW_BINARY_SHA),
            )

    def test_matching_discovery_is_preserved_until_full_review(self) -> None:
        baseline = reviewed(OLD_SHA)
        candidate_input = discovery(NEW_SHA, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(NEW_SHA), baseline=baseline, candidate=candidate_input
        )
        self.assertIs(selected, baseline)
        self.assertIs(candidate, candidate_input)
        self.assertEqual(disposition, "preserved payload-discovery candidate")
        self.assertTrue(normalized["changed"])
        self.assertEqual(normalized["reviewed_installer_sha256"], OLD_SHA)

    def test_matching_full_proposal_supersedes_live_discovery(self) -> None:
        baseline = reviewed(OLD_SHA)
        proposal = reviewed(NEW_SHA, "1.1.22", NEW_BINARY_SHA)
        live_candidate = discovery(NEW_SHA, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(NEW_SHA),
            baseline=baseline,
            live_candidate=live_candidate,
            proposal=proposal,
            candidate=live_candidate,
        )
        self.assertIs(selected, proposal)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "preserved full proposed evidence")
        self.assertFalse(normalized["changed"])
        self.assertEqual(normalized["reviewed_installer_sha256"], NEW_SHA)

    def test_full_proposal_may_refresh_payload_behind_same_installer(self) -> None:
        baseline = reviewed(OLD_SHA)
        proposal = reviewed(OLD_SHA, "1.1.22", NEW_BINARY_SHA)
        live_candidate = discovery(OLD_SHA, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(OLD_SHA),
            baseline=baseline,
            live_candidate=live_candidate,
            proposal=proposal,
            candidate=live_candidate,
        )
        self.assertIs(selected, proposal)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "preserved full proposed evidence")
        self.assertFalse(normalized["changed"])

    def test_fresh_live_payload_invalidates_stale_full_proposal(self) -> None:
        baseline = reviewed(OLD_SHA)
        stale_full = reviewed(OLD_SHA, "1.1.21", NEW_BINARY_SHA)
        newest_payload_sha = "f" * 64
        live_candidate = discovery(OLD_SHA, newest_payload_sha)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(OLD_SHA),
            baseline=baseline,
            live_candidate=live_candidate,
            proposal=stale_full,
            candidate=discovery(OLD_SHA, NEW_BINARY_SHA),
        )
        self.assertIs(selected, baseline)
        self.assertIs(candidate, live_candidate)
        self.assertEqual(
            disposition, "live payload change detected statically with reviewed installer"
        )
        self.assertEqual(candidate["payload"]["sha256"], newest_payload_sha)
        self.assertFalse(normalized["changed"])

    def test_stale_proposal_and_discovery_are_not_preserved(self) -> None:
        baseline = reviewed(OLD_SHA)
        stale_review = reviewed("d" * 64, "1.1.20", NEW_BINARY_SHA)
        stale_discovery = discovery("d" * 64, NEW_BINARY_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(NEW_SHA),
            baseline=baseline,
            proposal=stale_review,
            candidate=stale_discovery,
        )
        self.assertIs(selected, baseline)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "baseline review + live detection")
        self.assertTrue(normalized["changed"])

    def test_live_reviewed_pair_supersedes_stale_branch_candidate(self) -> None:
        baseline = reviewed(OLD_SHA)
        selected, normalized, candidate, disposition = self.reconcile(
            live=detection(OLD_SHA),
            baseline=baseline,
            live_candidate=discovery(OLD_SHA, BINARY_SHA),
            candidate=discovery(OLD_SHA, NEW_BINARY_SHA),
        )
        self.assertIs(selected, baseline)
        self.assertIsNone(candidate)
        self.assertEqual(disposition, "baseline review + live detection")
        self.assertFalse(normalized["changed"])

    def test_proposal_cannot_change_human_owned_policy(self) -> None:
        baseline = reviewed(OLD_SHA)
        proposal = reviewed(NEW_SHA, "1.1.22", NEW_BINARY_SHA)
        proposal["legal_and_distribution"] = deepcopy(proposal["legal_and_distribution"])
        proposal["legal_and_distribution"]["redistribution_permission_confirmed"] = True
        with self.assertRaisesRegex(MODULE.ReconcileError, "human-owned legal_and_distribution"):
            self.reconcile(live=detection(NEW_SHA), baseline=baseline, proposal=proposal)

    def test_discovery_cannot_change_fixed_origin(self) -> None:
        baseline = reviewed(OLD_SHA)
        candidate = discovery(NEW_SHA, NEW_BINARY_SHA)
        candidate["installer"]["final_url"] = "https://antigravity.google/docs"
        with self.assertRaisesRegex(MODULE.ReconcileError, "fixed official URL"):
            self.reconcile(live=detection(NEW_SHA), baseline=baseline, candidate=candidate)

    def test_live_detection_must_remain_on_reviewed_origin(self) -> None:
        baseline = reviewed(OLD_SHA)
        bad = detection(NEW_SHA)
        bad["installer"]["final_url"] = "https://example.invalid/install.sh"
        with self.assertRaisesRegex(MODULE.ReconcileError, "reviewed official HTTPS origin"):
            self.reconcile(live=bad, baseline=baseline)


if __name__ == "__main__":
    unittest.main()
