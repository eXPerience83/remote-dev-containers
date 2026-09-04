#!/usr/bin/env python3
"""Offline mutation tests for the Renovate ownership validator."""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("renovate_ownership", ROOT / "scripts/validate-renovate-ownership.py")
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class RenovateOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))

    def assert_rejected(self, mutate) -> None:
        candidate = copy.deepcopy(self.config)
        mutate(candidate)
        with self.assertRaises(VALIDATOR.OwnershipError):
            VALIDATOR.validate_config(candidate)

    def write_fixture_repo(self, root: Path) -> None:
        (root / "images/base").mkdir(parents=True)
        (root / ".github/workflows").mkdir(parents=True)
        for relative in ("renovate.json", "versions.env", "images/base/Dockerfile", "CHANGELOG.md"):
            source = ROOT / relative
            target = root / relative
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        (root / ".github/workflows/test.yml").write_text(
            "steps:\n  - uses: actions/checkout@" + "a" * 40 + " # v4\n", encoding="utf-8"
        )

    def apply_ubuntu_changelog_update(self, text: str, new_value: str, new_digest: str) -> str:
        manager = self.config["customManagers"][1]
        pattern = re.compile(VALIDATOR.python_regex(manager["matchStrings"][0]))
        matches = list(pattern.finditer(text))
        self.assertEqual(len(matches), 1)
        match = matches[0]
        replacement = manager["autoReplaceStringTemplate"]
        replacements = {
            "{{{currentValue}}}": match["currentValue"],
            "{{{currentDigest}}}": match["currentDigest"],
            "{{{newValue}}}": new_value,
            "{{{newDigest}}}": new_digest,
        }
        for token, value in replacements.items():
            replacement = replacement.replace(token, value)
        self.assertNotIn("{{{", replacement)
        return text[: match.start()] + replacement + text[match.end() :]

    def test_repository_contract(self) -> None:
        VALIDATOR.validate(ROOT)

    def test_automerge_cannot_be_enabled(self) -> None:
        self.assert_rejected(lambda config: config.update(automerge=True))

    def test_terminal_automerge_guard_is_required(self) -> None:
        self.assert_rejected(lambda config: config["packageRules"].pop())

    def test_terminal_automerge_guard_must_be_last(self) -> None:
        self.assert_rejected(lambda config: config["packageRules"].append({"matchManagers": ["github-actions"]}))

    def test_terminal_automerge_guard_cannot_enable_automerge(self) -> None:
        self.assert_rejected(lambda config: config["packageRules"][-1].update(automerge=True))

    def test_local_package_rule_cannot_enable_automerge(self) -> None:
        self.assert_rejected(
            lambda config: config["packageRules"].insert(
                -1, {"matchManagers": ["github-actions"], "automerge": True}
            )
        )

    def test_unapproved_managers_are_rejected(self) -> None:
        for manager in ("npm", "mise", "docker-compose"):
            with self.subTest(manager=manager):
                self.assert_rejected(lambda config, value=manager: config["enabledManagers"].append(value))

    def test_missing_mise_exclusion_is_rejected(self) -> None:
        self.assert_rejected(
            lambda config: config.update(
                packageRules=[rule for rule in config["packageRules"] if rule.get("matchManagers") != ["mise"]]
            )
        )

    def test_native_dockerfile_default_deny_is_required(self) -> None:
        self.assert_rejected(
            lambda config: config.update(
                packageRules=[
                    rule
                    for rule in config["packageRules"]
                    if rule != VALIDATOR.DOCKERFILE_DEFAULT_DENY
                ]
            )
        )

    def test_frontend_allow_is_required(self) -> None:
        self.assert_rejected(
            lambda config: config.update(
                packageRules=[
                    rule
                    for rule in config["packageRules"]
                    if rule != VALIDATOR.DOCKERFILE_FRONTEND_ALLOW
                ]
            )
        )

    def test_frontend_allow_cannot_be_broadened(self) -> None:
        def broaden_frontend_allow(config) -> None:
            rule = next(rule for rule in config["packageRules"] if rule.get("enabled") is True)
            rule["matchPackageNames"].append("example/unapproved-image")

        self.assert_rejected(broaden_frontend_allow)

    def test_unapproved_native_dockerfile_dependency_cannot_be_enabled(self) -> None:
        self.assert_rejected(
            lambda config: config["packageRules"].insert(
                -1,
                {
                    "matchManagers": ["dockerfile"],
                    "matchPackageNames": ["example/unapproved-image"],
                    "enabled": True,
                },
            )
        )

    def test_ubuntu_cannot_be_enabled_through_native_dockerfile_manager(self) -> None:
        self.assert_rejected(
            lambda config: config["packageRules"].insert(
                -1,
                {
                    "matchManagers": ["dockerfile"],
                    "matchPackageNames": ["ubuntu"],
                    "enabled": True,
                },
            )
        )

    def test_frontend_allow_must_follow_default_deny(self) -> None:
        def move_default_deny_after_allow(config) -> None:
            rules = config["packageRules"]
            default_deny = next(rule for rule in rules if rule == VALIDATOR.DOCKERFILE_DEFAULT_DENY)
            rules.remove(default_deny)
            allow_index = next(index for index, rule in enumerate(rules) if rule.get("enabled") is True)
            rules.insert(allow_index + 1, default_deny)

        self.assert_rejected(move_default_deny_after_allow)

    def test_non_object_custom_manager_is_rejected(self) -> None:
        self.assert_rejected(lambda config: config.update(customManagers=[None]))

    def test_extra_custom_runtime_manager_is_rejected(self) -> None:
        self.assert_rejected(lambda config: config["customManagers"].append({"customType": "regex"}))

    def test_changelog_manager_cannot_target_workflows(self) -> None:
        self.assert_rejected(
            lambda config: config["customManagers"][1].update(managerFilePatterns=[r"/^\.github/workflows/.*\.yml$/"])
        )

    def test_changelog_template_cannot_omit_previous_runtime_identity(self) -> None:
        self.assert_rejected(
            lambda config: config["customManagers"][1].update(
                autoReplaceStringTemplate="{{{newValue}}}@{{{newDigest}}}"
            )
        )

    def test_ubuntu_values_must_remain_synchronized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture_repo(root)
            dockerfile = root / "images/base/Dockerfile"
            version_line = next(
                line
                for line in (root / "versions.env").read_text(encoding="utf-8").splitlines()
                if line.startswith("UBUNTU_VERSION=")
            )
            dockerfile.write_text(
                dockerfile.read_text(encoding="utf-8").replace(
                    f"ARG {version_line}", "ARG UBUNTU_VERSION=99.98", 1
                ),
                encoding="utf-8",
            )
            with self.assertRaises(VALIDATOR.OwnershipError):
                VALIDATOR.validate(root)

    def test_ubuntu_from_must_consume_synchronized_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture_repo(root)
            dockerfile = root / "images/base/Dockerfile"
            dockerfile.write_text(
                dockerfile.read_text(encoding="utf-8").replace(
                    VALIDATOR.UBUNTU_FROM, "FROM example/unowned-image:fixed"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(VALIDATOR.OwnershipError):
                VALIDATOR.validate(root)

    def test_runtime_affecting_update_requires_matching_changelog_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture_repo(root)
            new_digest = "sha256:" + "b" * 64
            old_digest_line = next(
                line
                for line in (root / "versions.env").read_text(encoding="utf-8").splitlines()
                if line.startswith("UBUNTU_DIGEST=")
            )
            old_digest = old_digest_line.removeprefix("UBUNTU_DIGEST=")
            for relative in ("versions.env", "images/base/Dockerfile"):
                path = root / relative
                path.write_text(path.read_text(encoding="utf-8").replace(old_digest, new_digest), encoding="utf-8")

            with self.assertRaises(VALIDATOR.OwnershipError):
                VALIDATOR.validate(root)

            changelog = root / "CHANGELOG.md"
            updated = self.apply_ubuntu_changelog_update(changelog.read_text(encoding="utf-8"), "26.04", new_digest)
            changelog.write_text(updated, encoding="utf-8")
            VALIDATOR.validate(root)
            self.assertIn(f"Ubuntu LTS base 26.04@{old_digest} → 26.04@{new_digest}.", updated)

    def test_runtime_provenance_refresh_is_deterministic_and_append_only(self) -> None:
        original = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        first_digest = "sha256:" + "b" * 64
        second_digest = "sha256:" + "c" * 64
        first = self.apply_ubuntu_changelog_update(original, "26.04", first_digest)
        repeated = self.apply_ubuntu_changelog_update(original, "26.04", first_digest)
        self.assertEqual(first, repeated)

        second = self.apply_ubuntu_changelog_update(first, "26.04", second_digest)
        first_line = f"Ubuntu LTS base 26.04@{self._current_digest(original)} → 26.04@{first_digest}."
        second_line = f"Ubuntu LTS base 26.04@{first_digest} → 26.04@{second_digest}."
        self.assertEqual(second.count(first_line), 1)
        self.assertEqual(second.count(second_line), 1)
        self.assertLess(second.index(first_line), second.index(second_line))
        self.assertLess(second.index(second_line), second.index(VALIDATOR.UBUNTU_CHANGELOG_END))

        original_prefix = original.split(VALIDATOR.UBUNTU_CHANGELOG_START, 1)[0]
        original_suffix = original.split(VALIDATOR.UBUNTU_CHANGELOG_END, 1)[1]
        self.assertTrue(second.startswith(original_prefix + VALIDATOR.UBUNTU_CHANGELOG_START))
        self.assertTrue(second.endswith(VALIDATOR.UBUNTU_CHANGELOG_END + original_suffix))

    def _current_digest(self, text: str) -> str:
        pattern = re.compile(VALIDATOR.python_regex(self.config["customManagers"][1]["matchStrings"][0]))
        match = pattern.search(text)
        self.assertIsNotNone(match)
        assert match is not None
        return match["currentDigest"]

    def test_github_action_only_update_does_not_require_runtime_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture_repo(root)
            changelog = root / "CHANGELOG.md"
            before = changelog.read_text(encoding="utf-8")
            workflow = root / ".github/workflows/test.yml"
            workflow.write_text(
                workflow.read_text(encoding="utf-8").replace("a" * 40, "b" * 40),
                encoding="utf-8",
            )
            VALIDATOR.validate(root)
            self.assertEqual(changelog.read_text(encoding="utf-8"), before)
            self.assertNotIn("GitHub Action", before.split(VALIDATOR.UBUNTU_CHANGELOG_START, 1)[1].split(VALIDATOR.UBUNTU_CHANGELOG_END, 1)[0])

    def test_changelog_anchor_must_stay_inside_machine_owned_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_fixture_repo(root)
            changelog = root / "CHANGELOG.md"
            text = changelog.read_text(encoding="utf-8")
            pattern = re.compile(VALIDATOR.python_regex(self.config["customManagers"][1]["matchStrings"][0]))
            match = pattern.search(text)
            self.assertIsNotNone(match)
            assert match is not None
            anchor = match.group(0)
            text = text.replace(anchor + "\n" + VALIDATOR.UBUNTU_CHANGELOG_END, VALIDATOR.UBUNTU_CHANGELOG_END + "\n" + anchor, 1)
            changelog.write_text(text, encoding="utf-8")
            with self.assertRaises(VALIDATOR.OwnershipError):
                VALIDATOR.validate(root)


if __name__ == "__main__":
    unittest.main()
