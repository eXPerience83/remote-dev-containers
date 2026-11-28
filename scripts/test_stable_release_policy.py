#!/usr/bin/env python3
"""Offline regression tests for Stable dispatch identity; no API or registry writes."""

import importlib.util
import hashlib
import io
import json
import zipfile
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
        self.edge_run = {"id": 123, "run_attempt": 2, "head_sha": SHA}
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
                     patch.object(policy.subprocess, "check_output") as download:
                    with self.assertRaises(policy.ReleasePolicyError):
                        policy.read_edge_receipt(self.edge_run)
                    download.assert_not_called()

    def receipt_archive(self, filename="edge-promotion-receipt.json", extra=False):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as bundle:
            bundle.writestr(filename, json.dumps(self.receipt))
            if extra:
                bundle.writestr("other", "unexpected")
        return stream.getvalue()

    def test_artifact_id_run_and_digest_are_bound(self):
        archive = self.receipt_archive()
        artifact = {
            "name": "edge-promotion-receipt-2", "expired": False, "id": 321,
            "size_in_bytes": len(archive), "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
            "workflow_run": {"id": 123, "head_sha": SHA, "head_branch": "main",
                             "repository_id": 1309214441, "head_repository_id": 1309214441},
        }
        with patch.object(policy, "api", return_value=[{"artifacts": [artifact]}]), \
             patch.object(policy.subprocess, "check_output", return_value=archive) as download:
            self.assertEqual(policy.read_edge_receipt(self.edge_run), self.receipt)
            download.assert_called_once_with(
                ["gh", "api", "--method", "GET",
                 "repos/experience83/remote-dev-containers/actions/artifacts/321/zip"], timeout=60)
        for key, value in (("id", True), ("digest", ""), ("size_in_bytes", 0),
                           ("workflow_run", dict(artifact["workflow_run"], head_sha=OTHER)),
                           ("workflow_run", dict(artifact["workflow_run"], id=124)),
                           ("workflow_run", dict(artifact["workflow_run"], head_repository_id=1))):
            with self.subTest(key=key, value=value), \
                 patch.object(policy, "api", return_value=[{"artifacts": [dict(artifact, **{key: value})]}]), \
                 patch.object(policy.subprocess, "check_output") as download:
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.read_edge_receipt(self.edge_run)
                download.assert_not_called()

    def test_bad_archive_shape_or_digest_rejected(self):
        archive = self.receipt_archive()
        digest = "sha256:" + hashlib.sha256(archive).hexdigest()
        for data, expected, size in (
            (archive, "sha256:" + "a" * 64, len(archive)),
            (archive, digest, len(archive) + 1),
            (archive + b"extra", digest, len(archive) + 5),
        ):
            with self.assertRaises(policy.ReleasePolicyError):
                policy.decode_edge_receipt(data, expected, size)
        for data in (self.receipt_archive("../edge-promotion-receipt.json"),
                     self.receipt_archive(extra=True), b"not zip"):
            with self.assertRaises(policy.ReleasePolicyError):
                policy.decode_edge_receipt(data, "sha256:" + hashlib.sha256(data).hexdigest(), len(data))

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

    def test_dry_run_cannot_enter_write_jobs(self):
        for mode in ("prepare-tag", "require-tag", "finalize"):
            with patch.dict(policy.os.environ, {"DRY_RUN": "true"}, clear=True), \
                 patch.object(policy, "write_api") as write, \
                 patch.object(policy.subprocess, "check_output") as command:
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.main(["--mode", mode])
                write.assert_not_called()
                command.assert_not_called()

    def test_retirement_or_stale_main_failure_prevents_tag_write(self):
        for guard in ("require_retired_publisher", "require_current_main"):
            with patch.object(policy, "require_retired_publisher"), \
                 patch.object(policy, "require_current_main"), \
                 patch.object(policy, guard, side_effect=policy.ReleasePolicyError("blocked")), \
                 patch.object(policy, "write_api") as write:
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.ensure_tag(self.tag, SHA)
                write.assert_not_called()

    def test_tag_readback_exact_not_prefix(self):
        for refs, expected in (([], False), ([self.ref], True),
                               ([dict(self.ref, ref=self.ref["ref"] + "-extra")], False)):
            with patch.object(policy, "api", return_value=refs):
                self.assertEqual(policy.read_tag(self.tag, SHA), expected)

    def test_tag_ruleset_requires_immutability_and_reports_creation(self):
        record = {"id": policy.TAG_RULESET, "target": "tag", "enforcement": "active",
                  "source_type": "Repository", "source": ENV["GITHUB_REPOSITORY"],
                  "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
                  "rules": [{"type": name} for name in ("creation", "deletion", "update", "non_fast_forward")]}
        self.assertTrue(policy.validate_tag_ruleset(record))
        self.assertFalse(policy.validate_tag_ruleset(dict(record, rules=record["rules"][1:])))
        for changed in (dict(record, enforcement="disabled"), dict(record, target="branch"),
                        dict(record, rules=record["rules"][:-1]),
                        dict(record, conditions={"ref_name": {"include": ["refs/tags/v*"], "exclude": ["refs/tags/v0.4.0"]}})):
            with self.assertRaises(policy.ReleasePolicyError):
                policy.validate_tag_ruleset(changed)

    def test_restricted_creation_never_attempts_write(self):
        with patch.object(policy, "require_retired_publisher"), \
             patch.object(policy, "require_current_main"), \
             patch.object(policy, "tag_creation_restricted", return_value=True), \
             patch.object(policy, "read_tag", return_value=False), \
             patch.object(policy, "write_api") as write:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.ensure_tag(self.tag, SHA)
            write.assert_not_called()

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
        empty = [{"total_count": 0, "workflow_runs": []}]
        with patch.object(policy, "api", side_effect=[record] + [empty] * 5):
            policy.require_retired_publisher()
        for pending in ([{"total_count": 1, "workflow_runs": []}],
                        [{"total_count": 0, "workflow_runs": [{"id": 4}]}], []):
            with patch.object(policy, "api", side_effect=[record, pending]):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.require_retired_publisher()
        for state in ("active", "disabled_inactivity", "deleted"):
            with patch.object(policy, "api", return_value=dict(record, state=state)):
                with self.assertRaises(policy.ReleasePolicyError):
                    policy.require_retired_publisher()

    def test_fresh_release_preflight_blocks_duplicate_release_and_conflicting_tag(self):
        with patch.object(policy, "find_release", return_value=self.record), \
             patch.object(policy.subprocess, "run") as command:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.require_fresh_release(self.tag, SHA)
            command.assert_not_called()
        with patch.object(policy, "find_release", return_value=None), \
             patch.object(policy, "read_tag", side_effect=policy.ReleasePolicyError("conflict")), \
             patch.object(policy.subprocess, "run") as command:
            with self.assertRaises(policy.ReleasePolicyError):
                policy.require_fresh_release(self.tag, SHA)
            command.assert_not_called()
        with patch.object(policy, "find_release", return_value=None), \
             patch.object(policy, "read_tag", return_value=False), \
             patch.object(policy.subprocess, "run") as command:
            policy.require_fresh_release(self.tag, SHA)
            self.assertEqual(command.call_args.args[0][-3:], ["--tag", self.tag, "--preflight-only"])

    def test_tag_creation_is_idempotent_and_requires_readback(self):
        for existing, after in ((True, True), (False, True), (False, False)):
            with patch.object(policy, "require_retired_publisher"), \
                 patch.object(policy, "require_current_main"), \
                 patch.object(policy, "tag_creation_restricted", return_value=False), \
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
                 patch.object(policy, "require_current_main"), \
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


class ReleaseFlowTests(unittest.TestCase):
    """Exercise the CLI flow with fake external commands, never GitHub/GHCR."""

    def setUp(self):
        self.base = "sha256:" + "1" * 64
        self.runtime = "sha256:" + "2" * 64
        self.stable_base = "sha256:" + "3" * 64
        self.stable_runtime = "sha256:" + "4" * 64
        self.tag = ENV["RELEASE_TAG"]
        self.main_sha = SHA
        self.tag_exists = False
        self.release = None
        self.creation_restricted = True
        self.legacy_state = "disabled_manually"
        self.registry_mismatch = False
        self.change_main_on_preflight = False
        self.posts = []
        self.alias_reads = []
        self.preflights = 0
        self.runs = WorkflowTests().fixtures()
        self.edge_run = next(run for run in self.runs
                             if run["workflow_id"] == policy.EDGE_WORKFLOW)
        receipt = {
            "source_sha": SHA, "run_id": str(self.edge_run["id"]),
            "run_attempt": str(self.edge_run["run_attempt"]),
            "base_digest": self.base, "runtime_digest": self.runtime,
        }
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("edge-promotion-receipt.json", json.dumps(receipt))
        self.archive = archive.getvalue()
        self.artifact = {
            "name": "edge-promotion-receipt-1", "expired": False, "id": 321,
            "size_in_bytes": len(self.archive),
            "digest": "sha256:" + hashlib.sha256(self.archive).hexdigest(),
            "workflow_run": {"id": self.edge_run["id"], "head_sha": SHA,
                             "head_branch": "main", "repository_id": 1309214441,
                             "head_repository_id": 1309214441},
        }

    def fake_response(self, endpoint):
        if endpoint == "git/ref/heads/main":
            return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.main_sha}}
        if endpoint == f"git/matching-refs/tags/{self.tag}":
            return [{"ref": f"refs/tags/{self.tag}", "object": {"type": "commit", "sha": SHA}}] if self.tag_exists else []
        if endpoint == f"actions/runs?head_sha={SHA}&per_page=100":
            return [{"workflow_runs": self.runs}]
        for run in self.runs:
            if endpoint == f"actions/runs/{run['id']}/attempts/1/jobs?per_page=100":
                return [{"jobs": [{"name": name, "status": "completed", "conclusion": "success"}
                                  for name in policy.REQUIRED_WORKFLOWS[run["workflow_id"]][2]]}]
        if endpoint == f"actions/runs/{self.edge_run['id']}/artifacts?per_page=100":
            return [{"artifacts": [self.artifact]}]
        if endpoint == f"rulesets/{policy.TAG_RULESET}":
            names = ["update", "deletion", "non_fast_forward"]
            if self.creation_restricted:
                names.append("creation")
            return {"id": policy.TAG_RULESET, "target": "tag", "enforcement": "active",
                    "source_type": "Repository", "source": ENV["GITHUB_REPOSITORY"],
                    "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
                    "rules": [{"type": name} for name in names]}
        if endpoint == f"actions/workflows/{policy.LEGACY_WORKFLOW}":
            return {"id": policy.LEGACY_WORKFLOW, "path": ".github/workflows/publish-amd64.yml",
                    "state": self.legacy_state}
        if endpoint.startswith(f"actions/workflows/{policy.LEGACY_WORKFLOW}/runs?status="):
            return [{"total_count": 0, "workflow_runs": []}]
        if endpoint == "releases?per_page=100":
            return [[self.release] if self.release else []]
        if endpoint == "releases/latest":
            return self.release
        self.fail(f"unexpected fixture GET: {endpoint}")

    def command(self, argv, **kwargs):
        if argv == ["git", "rev-parse", "HEAD"]:
            return SHA + "\n"
        if argv[:2] == ["gh", "api"]:
            prefix = "repos/" + policy.REPOSITORY + "/"
            endpoint = next(arg[len(prefix):] for arg in argv if arg.startswith(prefix))
            method = argv[argv.index("--method") + 1]
            if method == "GET":
                if endpoint == "actions/artifacts/321/zip":
                    return self.archive
                return json.dumps(self.fake_response(endpoint))
            self.assertEqual(method, "POST")
            payload = json.loads(kwargs["input"])
            self.posts.append((endpoint, payload))
            if endpoint == "git/refs":
                self.tag_exists = True
                return json.dumps({"ref": payload["ref"], "object": {"type": "commit", "sha": payload["sha"]}})
            if endpoint == "releases":
                self.release = dict(payload, id=42)
                return json.dumps(self.release)
            self.fail(f"unexpected fixture POST: {endpoint}")
        if argv[:3] == ["docker", "buildx", "imagetools"]:
            self.assertEqual(argv[3], "inspect")
            image, tag = argv[4].rsplit(":", 1)
            is_base = image.endswith("/remote-dev-base")
            if tag == "sha-" + SHA:
                return json.dumps(self.base if is_base else self.runtime)
            self.alias_reads.append((image, tag))
            digest = self.stable_base if is_base else self.stable_runtime
            if self.registry_mismatch and tag == "latest":
                digest = self.runtime
            return json.dumps(digest)
        self.fail(f"unexpected fixture command: {argv}")

    def preflight(self, argv, **kwargs):
        self.assertEqual(argv[-3:], ["--tag", self.tag, "--preflight-only"])
        self.assertTrue(kwargs["check"])
        self.preflights += 1
        if self.change_main_on_preflight:
            self.main_sha = OTHER

    def invoke(self, mode, dry_run=False):
        env = dict(ENV, DRY_RUN="true" if dry_run else "false",
                   ACCEPTED_EDGE_DIGEST=self.runtime, STABLE_BASE_DIGEST=self.stable_base,
                   STABLE_RUNTIME_DIGEST=self.stable_runtime)
        with patch.dict(policy.os.environ, env, clear=True), \
             patch.object(policy.Path, "read_text", return_value=PINS), \
             patch.object(policy.subprocess, "check_output", side_effect=self.command), \
             patch.object(policy.subprocess, "run", side_effect=self.preflight):
            policy.main(["--mode", mode])

    def test_complete_dry_run_reads_only(self):
        self.invoke("validate", dry_run=True)
        self.assertEqual(self.preflights, 1)
        self.assertEqual(self.posts, [])
        self.assertFalse(self.tag_exists)

    def test_dry_run_rechecks_main_after_registry_preflight(self):
        self.change_main_on_preflight = True
        with self.assertRaisesRegex(policy.ReleasePolicyError, "main changed"):
            self.invoke("validate", dry_run=True)
        self.assertEqual(self.posts, [])

    def test_prepare_tag_stops_on_retirement_or_creation_restriction(self):
        self.legacy_state = "active"
        with self.assertRaisesRegex(policy.ReleasePolicyError, "explicitly disabled"):
            self.invoke("prepare-tag")
        self.legacy_state = "disabled_manually"
        with self.assertRaisesRegex(policy.ReleasePolicyError, "creation is restricted"):
            self.invoke("prepare-tag")
        self.assertEqual(self.posts, [])

    def test_tag_and_release_flow_and_duplicate_protection(self):
        self.creation_restricted = False
        self.invoke("prepare-tag")
        self.assertEqual(self.posts, [("git/refs", {"ref": "refs/tags/" + self.tag, "sha": SHA})])
        self.invoke("require-tag")
        self.invoke("finalize")
        self.assertEqual([endpoint for endpoint, _ in self.posts], ["git/refs", "releases"])
        self.assertEqual(len(set(self.alias_reads)), 6)
        self.assertEqual(self.release["make_latest"], "true")
        self.invoke("finalize")
        self.assertEqual(len(self.posts), 2)
        with self.assertRaisesRegex(policy.ReleasePolicyError, "Release already exists"):
            self.invoke("prepare-tag")
        self.assertEqual(len(self.posts), 2)

    def test_alias_mismatch_blocks_release_post(self):
        self.tag_exists = True
        self.registry_mismatch = True
        with self.assertRaisesRegex(policy.ReleasePolicyError, "Stable alias differs"):
            self.invoke("finalize")
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
