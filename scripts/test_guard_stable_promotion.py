#!/usr/bin/env python3
"""Offline regression tests for immutable/monotonic stable registry promotion."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).with_name("guard-stable-promotion.py")
spec = importlib.util.spec_from_file_location("stable_promotion_guard", SOURCE)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

BASE = "ghcr.io/experience83/remote-dev-base@sha256:" + "a" * 64
RUNTIME = "ghcr.io/experience83/remote-dev@sha256:" + "b" * 64
OLD_BASE = "sha256:" + "c" * 64
OLD_RUNTIME = "sha256:" + "d" * 64


def aliases(base=None, runtime=None, base_tag=None, runtime_tag=None):
    return {
        ("remote-dev-base", "v0.3.0"): base_tag,
        ("remote-dev-base", "stable-amd64"): base,
        ("remote-dev", "v0.3.0"): runtime_tag,
        ("remote-dev", "stable"): runtime,
        ("remote-dev", "stable-amd64"): runtime,
        ("remote-dev", "latest"): runtime,
    }


def check(state, version="v0.3.0", old_version="v0.2.0"):
    with patch.object(guard, "read_tag", side_effect=lambda image, tag: state[(image, tag)]), \
         patch.object(guard, "image_release", return_value=old_version):
        return guard.validate(version, BASE, RUNTIME)


class GuardTests(unittest.TestCase):
    def test_fresh_first_publication(self):
        self.assertEqual(check(aliases())["mode"], "fresh")

    def test_monotonic_release_with_existing_consistent_stable(self):
        record = check(aliases(OLD_BASE, OLD_RUNTIME))
        self.assertEqual(record["mode"], "fresh")
        self.assertEqual(record["previous_version"], "v0.2.0")

    def test_reject_older_version_and_equal_version(self):
        for prior in ("v0.3.0", "v0.4.0", "v1.0.0"):
            with self.subTest(prior=prior), self.assertRaisesRegex(ValueError, "rollback|overwrite"):
                check(aliases(OLD_BASE, OLD_RUNTIME), old_version=prior)

    def test_same_digest_rerun_is_noop(self):
        record = check(aliases("sha256:"+"a"*64, "sha256:"+"b"*64,
                               "sha256:"+"a"*64, "sha256:"+"b"*64))
        self.assertEqual(record["mode"], "idempotent")

    def test_reject_same_tag_with_new_candidate_digest(self):
        state = aliases(OLD_BASE, OLD_RUNTIME, OLD_BASE, OLD_RUNTIME)
        with self.assertRaisesRegex(ValueError, "immutable SemVer"):
            check(state)

    def test_reject_partial_publication_and_alias_drift(self):
        state = aliases(None, None, "sha256:"+"a"*64, None)
        with self.assertRaisesRegex(ValueError, "partial version"):
            check(state)
        state = aliases(OLD_BASE, OLD_RUNTIME)
        state[("remote-dev", "latest")] = "sha256:"+"f"*64
        with self.assertRaisesRegex(ValueError, "aliases disagree"):
            check(state)
        state = aliases(None, OLD_RUNTIME)
        with self.assertRaisesRegex(ValueError, "base stable"):
            check(state)

    def test_reject_noncanonical_semver(self):
        for version in ("v00.3.0", "v0.03.0", "v0.3.00",
                        "v0.3.0-beta", "v0.3.0-extra", "v1.0.0+build"):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "canonical"):
                check(aliases(), version=version)

    def test_registry_failures_never_mean_tag_absent(self):
        with patch.object(guard, "run", return_value=subprocess.CompletedProcess(
            [], 1, "", "unauthorized: access denied")):
            with self.assertRaisesRegex(ValueError, "cannot inspect"):
                guard.read_tag("remote-dev", "stable")
        with patch.object(guard, "run", return_value=subprocess.CompletedProcess(
            [], 1, "", "manifest unknown")):
            self.assertIsNone(guard.read_tag("remote-dev", "v0.3.0"))

        # CodeRabbit's reported false-PASS: a token endpoint can return 404
        # while the tag itself still exists. It must never mean "fresh".
        ref = "ghcr.io/experience83/remote-dev:v0.3.0"
        failures = (
            "failed to authorize: failed to fetch anonymous token: "
            "unexpected status: 404 Not Found",
            "failed to authorize: failed to fetch anonymous token: "
            "manifest unknown",
            "authorization failed: requested " + ref + ": not found",
            "unexpected status: 404 Not Found",
            "failed to fetch token: 404 Not Found",
            "connection refused: " + ref + ": not found",
        )
        for error in failures:
            with self.subTest(error=error):
                with patch.object(guard, "run", return_value=subprocess.CompletedProcess(
                    [], 1, "", error)):
                    with self.assertRaisesRegex(ValueError, "cannot inspect"):
                        guard.read_tag("remote-dev", "v0.3.0")

        # Explicit missing manifests and the exact requested tag are absent.
        for missing in ("manifest unknown", "manifest not found",
                        "ERROR: " + ref + ": not found"):
            with self.subTest(missing=missing):
                with patch.object(guard, "run", return_value=subprocess.CompletedProcess(
                    [], 1, "", missing)):
                    self.assertIsNone(guard.read_tag("remote-dev", "v0.3.0"))

    def test_failed_old_image_lookup_cannot_downgrade(self):
        with patch.object(guard, "read_tag", side_effect=lambda image, tag:
                          aliases(OLD_BASE, OLD_RUNTIME)[(image, tag)]), \
             patch.object(guard, "image_release", side_effect=ValueError("pull failed")):
            with self.assertRaisesRegex(ValueError, "pull failed"):
                guard.validate("v0.3.0", BASE, RUNTIME)


if __name__ == "__main__":
    unittest.main()
