#!/usr/bin/env python3
"""Offline regression tests for Stable dispatch identity; no API or registry writes."""

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "stable_release_policy", Path(__file__).with_name("stable-release-policy.py")
)
policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(policy)

SHA = "a" * 40
OTHER = "b" * 40
ENV = {
    "GITHUB_REPOSITORY": "eXPerience83/remote-dev-containers",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_ACTOR_ID": "16572400",
    "GITHUB_RUN_ATTEMPT": "1",
    "DRY_RUN": "false",
    "RELEASE_SHA": SHA,
    "GITHUB_SHA": SHA,
    "GITHUB_WORKFLOW_SHA": SHA,
    "RELEASE_TAG": "v0.4.0",
}
PINS = "# Reviewed version\nBASE_VERSION=0.4.0\n"


class DispatchTests(unittest.TestCase):
    def test_exact_owner_dispatch_and_dry_run(self):
        for dry_run in ("true", "false"):
            with self.subTest(dry_run=dry_run):
                self.assertEqual(
                    policy.validate_dispatch(dict(ENV, DRY_RUN=dry_run), PINS, SHA, SHA),
                    ("v0.4.0", SHA),
                )

    def test_untrusted_contexts(self):
        for key, value in (
            ("GITHUB_REPOSITORY", "someone/remote-dev-containers"),
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_REF", "refs/tags/v0.4.0"),
            ("GITHUB_REF", "refs/heads/topic"),
            ("GITHUB_ACTOR_ID", "1"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("DRY_RUN", ""),
            ("RELEASE_SHA", "a" * 7),
            ("RELEASE_SHA", "A" * 40),
            ("GITHUB_SHA", OTHER),
            ("GITHUB_WORKFLOW_SHA", OTHER),
            ("RELEASE_TAG", "v0.04.0"),
            ("RELEASE_TAG", "v0.4.0-beta.1"),
            ("RELEASE_TAG", "v0.4.1"),
            ("RELEASE_TAG", "v0.4.0\n"),
        ):
            with self.subTest(key=key, value=value):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_dispatch(dict(ENV, **{key: value}), PINS, SHA, SHA)

    def test_stale_main_or_wrong_checkout(self):
        for main, checkout in ((OTHER, SHA), (SHA, OTHER), ("", SHA)):
            with self.subTest(main=main, checkout=checkout):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_dispatch(ENV, PINS, main, checkout)

    def test_noncanonical_or_duplicate_pin(self):
        for pins in (
            "", "BASE_VERSION=0.4.1", "BASE_VERSION=0.4.0-beta.1",
            "BASE_VERSION=0.4.0 # comment", "BASE_VERSION=$(echo 0.4.0)",
            PINS + "BASE_VERSION=0.4.0\n", PINS + "export BASE_VERSION=0.4.1\n",
            PINS + " BASE_VERSION=0.4.1\n",
        ):
            with self.subTest(pins=pins):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_dispatch(ENV, pins, SHA, SHA)

    def test_missing_context_values(self):
        for key in ENV:
            with self.subTest(key=key):
                env = dict(ENV)
                del env[key]
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_dispatch(env, PINS, SHA, SHA)



class WorkflowTests(unittest.TestCase):
    def fixtures(self):
        return [
            {
                "workflow_id": workflow, "path": path, "event": sorted(events)[0],
                "head_sha": SHA, "head_branch": "main", "id": index + 1,
                "run_attempt": 1, "status": "completed", "conclusion": "success",
            }
            for index, (workflow, (path, events, _)) in enumerate(
                policy.REQUIRED_WORKFLOWS.items()
            )
        ]

    def test_exact_main_across_pages(self):
        runs = self.fixtures()
        actual = policy.validate_runs([
            {"workflow_runs": runs[:1]}, {"workflow_runs": runs[1:]}
        ], SHA)
        self.assertEqual(set(actual), set(policy.REQUIRED_WORKFLOWS))

    def test_missing_or_wrong_identity_is_rejected(self):
        for key, value in (
            ("head_sha", OTHER), ("head_branch", "topic"),
            ("workflow_id", 999), ("path", ".github/workflows/forged.yml"),
            ("event", "pull_request"),
        ):
            with self.subTest(key=key):
                runs = self.fixtures()
                runs[0][key] = value
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_runs([{"workflow_runs": runs}], SHA)

    def test_latest_failure_blocks_older_success(self):
        for status, conclusion in (
            ("in_progress", None), ("completed", "failure"),
            ("completed", "skipped"), ("completed", "cancelled"),
        ):
            with self.subTest(status=status, conclusion=conclusion):
                runs = self.fixtures()
                runs.append(dict(runs[0], id=999, status=status, conclusion=conclusion))
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_runs([{"workflow_runs": runs}], SHA)

    def test_irrelevant_newer_runs_do_not_replace_required_evidence(self):
        runs = self.fixtures()
        runs.extend([dict(runs[0], id=999, head_branch="topic", conclusion="failure"),
                     dict(runs[0], id=1000, head_sha=OTHER, conclusion="failure")])
        result = policy.validate_runs([{"workflow_runs": runs}], SHA)
        self.assertEqual(result[runs[0]["workflow_id"]]["id"], 1)

    def test_every_required_job_must_succeed_once(self):
        for workflow, (_, _, expected) in policy.REQUIRED_WORKFLOWS.items():
            jobs = [{"name": name, "status": "completed", "conclusion": "success"}
                    for name in sorted(expected)]
            policy.validate_jobs([{"jobs": jobs}], workflow)
            for changed in (
                jobs[1:], jobs + [jobs[0]],
                [dict(jobs[0], conclusion="skipped")] + jobs[1:],
                [dict(jobs[0], status="in_progress")] + jobs[1:],
            ):
                with self.subTest(workflow=workflow, changed=changed):
                    with self.assertRaises(policy.ReleasePolicyError):
                        policy.validate_jobs([{"jobs": changed}], workflow)


class EdgeAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.edge_run = {"id": 123, "run_attempt": 2}
        self.base = "sha256:" + "1" * 64
        self.runtime = "sha256:" + "2" * 64
        self.receipt = {
            "source_sha": SHA, "run_id": "123", "run_attempt": "2",
            "base_digest": self.base, "runtime_digest": self.runtime,
        }

    def test_exact_receipt(self):
        self.assertEqual(
            policy.validate_edge_receipt(self.receipt, SHA, self.edge_run, self.runtime),
            (self.base, self.runtime),
        )

    def test_other_source_attempt_or_digest_rejected(self):
        for key, value in (
            ("source_sha", OTHER), ("run_id", "124"), ("run_attempt", "1"),
            ("base_digest", "sha256:bad"), ("runtime_digest", self.base),
        ):
            with self.subTest(key=key):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_edge_receipt(
                        dict(self.receipt, **{key: value}), SHA, self.edge_run, self.runtime
                    )
        for invalid in ("", "edge-amd64", self.base, self.runtime.upper()):
            with self.subTest(accepted=invalid):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_edge_receipt(self.receipt, SHA, self.edge_run, invalid)

    def test_missing_or_extra_receipt_fields(self):
        for receipt in ({}, [], dict(self.receipt, extra=True)):
            with self.subTest(receipt=receipt):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.validate_edge_receipt(receipt, SHA, self.edge_run, self.runtime)

    def test_missing_expired_ambiguous_or_oversized_artifact(self):
        artifact = {"name": "edge-promotion-receipt-2", "expired": False, "size_in_bytes": 500}
        for artifacts in (
            [], [dict(artifact, name="edge-promotion-receipt-1")],
            [dict(artifact, expired=True)], [artifact, artifact],
            [dict(artifact, size_in_bytes=16385)],
        ):
            with self.subTest(artifacts=artifacts):
                with patch.object(policy, "api", return_value=[{"artifacts": artifacts}]), \
                     patch.object(policy.subprocess, "run") as download:
                    with self.assertRaises(policy.ReleasePolicyError):
                        policy.read_edge_receipt(self.edge_run)
                    download.assert_not_called()

    def test_registry_aliases_must_match_both_indexes(self):
        for values in ((self.base, self.runtime), (self.runtime, self.runtime),
                       (self.base, self.base)):
            with self.subTest(values=values):
                with patch.object(policy, "read_edge_receipt", return_value=self.receipt), \
                     patch.object(policy, "read_registry_digest", side_effect=values):
                    if values == (self.base, self.runtime):
                        policy.verify_accepted_edge(SHA, self.edge_run, self.runtime)
                    else:
                        with self.assertRaises(policy.ReleasePolicyError):
                            policy.verify_accepted_edge(SHA, self.edge_run, self.runtime)


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.tag = "v0.4.0"
        self.base = "sha256:" + "1" * 64
        self.runtime = "sha256:" + "2" * 64
        self.edge = "sha256:" + "3" * 64
        self.ref = {"ref": "refs/tags/" + self.tag,
                    "object": {"type": "commit", "sha": SHA}}
        self.record = dict(policy.release_fields(
            self.tag, SHA, self.base, self.runtime, self.edge), id=123)

    def test_tag_readback_exact_not_prefix(self):
        for refs, expected in (([], False), ([self.ref], True),
                               ([dict(self.ref, ref=self.ref["ref"] + "-extra")], False)):
            with patch.object(policy, "api", return_value=refs):
                self.assertEqual(policy.read_tag(self.tag, SHA), expected)

    def test_tag_conflict_rejected(self):
        for refs in ([dict(self.ref, object={"type": "commit", "sha": OTHER})],
                     [dict(self.ref, object={"type": "tag", "sha": SHA})],
                     [self.ref, self.ref]):
            with patch.object(policy, "api", return_value=refs):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.read_tag(self.tag, SHA)

    def test_legacy_requires_explicit_disable(self):
        record = {"id": policy.LEGACY_WORKFLOW, "path": ".github/workflows/publish-amd64.yml",
                  "state": "disabled_manually"}
        with patch.object(policy, "api", return_value=record):
            policy.require_retired_publisher()
        for state in ("active", "disabled_inactivity", "deleted"):
            with patch.object(policy, "api", return_value=dict(record, state=state)):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.require_retired_publisher()

    def test_tag_creation_is_idempotent_and_requires_readback(self):
        for existing, after in ((True, True), (False, True), (False, False)):
            with patch.object(policy, "require_retired_publisher"), \
                 patch.object(policy, "require_current_main"), \
                 patch.object(policy, "read_tag", side_effect=[existing, after]), \
                 patch.object(policy, "write_api") as write:
                if not after:
                    with self.assertRaises(policy.ReleasePolicyError):
                        policy.ensure_tag(self.tag, SHA)
                else:
                    policy.ensure_tag(self.tag, SHA)
                if existing:
                    write.assert_not_called()
                else:
                    write.assert_called_once_with("git/refs", {"ref": self.ref["ref"], "sha": SHA})

    def test_all_six_stable_aliases_required(self):
        expected = [self.base] * 2 + [self.runtime] * 4
        with patch.object(policy, "read_image_tag_digest", side_effect=expected) as read:
            policy.verify_stable_aliases(self.tag, self.base, self.runtime)
            self.assertEqual(read.call_count, 6)
        for i in range(6):
            bad = expected.copy()
            bad[i] = self.edge
            with patch.object(policy, "read_image_tag_digest", side_effect=bad):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.verify_stable_aliases(self.tag, self.base, self.runtime)

    def test_release_existing_or_created_must_match_and_be_latest(self):
        for existing in (None, self.record):
            with patch.object(policy, "require_tag"), \
                 patch.object(policy, "verify_stable_aliases"), \
                 patch.object(policy, "find_release", side_effect=[existing, self.record]), \
                 patch.object(policy, "write_api", return_value=self.record) as write, \
                 patch.object(policy, "api", return_value={"id": 123}):
                policy.finalize_release(self.tag, SHA, self.base, self.runtime, self.edge)
                self.assertEqual(write.call_count, 0 if existing else 1)

    def test_no_release_on_alias_failure_or_conflicting_record(self):
        with patch.object(policy, "require_tag"), \
             patch.object(policy, "verify_stable_aliases", side_effect=policy.ReleasePolicyError("alias")), \
             patch.object(policy, "write_api") as write:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.finalize_release(self.tag, SHA, self.base, self.runtime, self.edge)
            write.assert_not_called()
        with patch.object(policy, "require_tag"), \
             patch.object(policy, "verify_stable_aliases"), \
             patch.object(policy, "find_release", return_value=dict(self.record, draft=True)), \
             patch.object(policy, "write_api") as write:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.finalize_release(self.tag, SHA, self.base, self.runtime, self.edge)
            write.assert_not_called()

if __name__ == "__main__":
    unittest.main()
