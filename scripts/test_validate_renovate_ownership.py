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

    def test_unapproved_managers_are_rejected(self) -> None:
        for manager in ("npm", "mise", "docker-compose"):
            with self.subTest(manager=manager):
                self.assert_rejected(lambda config, value=manager: config["enabledManagers"].append(value))

    def test_missing_mise_exclusion_is_rejected(self) -> None:
        self.assert_rejected(lambda config: config.update(packageRules=config["packageRules"][:-1]))

    def test_native_ubuntu_overlap_is_rejected(self) -> None:
        def enable_native(config) -> None:
            config["packageRules"][0]["enabled"] = True
        self.assert_rejected(enable_native)

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
