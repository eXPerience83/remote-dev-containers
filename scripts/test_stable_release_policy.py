#!/usr/bin/env python3
"""Offline regression tests for Stable dispatch identity; no API or registry writes."""

import importlib.util
from pathlib import Path
import unittest

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

if __name__ == "__main__":
    unittest.main()
