#!/usr/bin/env python3
"""Offline mutation tests for the Renovate ownership validator."""

from __future__ import annotations

import copy
import importlib.util
import json
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
            default_deny = next(
                rule
                for rule in rules
                if rule == VALIDATOR.DOCKERFILE_DEFAULT_DENY
            )
            rules.remove(default_deny)
            allow_index = next(index for index, rule in enumerate(rules) if rule.get("enabled") is True)
            rules.insert(allow_index + 1, default_deny)

        self.assert_rejected(move_default_deny_after_allow)

    def test_non_object_custom_manager_is_rejected(self) -> None:
        self.assert_rejected(lambda config: config.update(customManagers=[None]))

    def test_extra_custom_runtime_manager_is_rejected(self) -> None:
        self.assert_rejected(lambda config: config["customManagers"].append({"customType": "regex"}))

    def test_ubuntu_regex_must_match_both_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "images/base").mkdir(parents=True)
            (root / ".github/workflows").mkdir(parents=True)
            for relative in ("renovate.json", "versions.env", "images/base/Dockerfile"):
                source = ROOT / relative
                target = root / relative
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            (root / ".github/workflows/test.yml").write_text(
                "steps:\n  - uses: actions/checkout@" + "a" * 40 + " # v4\n", encoding="utf-8"
            )
            dockerfile = root / "images/base/Dockerfile"
            dockerfile.write_text(
                dockerfile.read_text(encoding="utf-8").replace("ARG UBUNTU_VERSION=", "ARG DISTRO_VERSION="),
                encoding="utf-8",
            )
            with self.assertRaises(VALIDATOR.OwnershipError):
                VALIDATOR.validate(root)


if __name__ == "__main__":
    unittest.main()
