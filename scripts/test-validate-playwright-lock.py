#!/usr/bin/env python3
"""Offline regression checks for the Playwright npm lock validator."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("validate-playwright-lock.py")
spec = importlib.util.spec_from_file_location("validate_playwright_lock", SOURCE)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

root = SOURCE.parent.parent
package = json.loads((root / "config/playwright-package.json").read_text())
lock = json.loads((root / "config/playwright-package-lock.json").read_text())
version = module.checked_version((root / "versions.env").read_text())


class NpmLockContractTests(unittest.TestCase):
    def test_exact_reviewed_graph_passes(self):
        module.validate(package, lock, version)

    def test_stale_reviewed_version_rejected(self):
        with self.assertRaises(module.BadLock):
            module.validate(package, lock, "0.0.83")

    def test_unexpected_dependency_rejected(self):
        modified = copy.deepcopy(lock)
        modified["packages"]["node_modules/unexpected"] = {"version": "1.0.0"}
        with self.assertRaises(module.BadLock):
            module.validate(package, modified, version)

    def test_integrity_absent_rejected(self):
        modified = copy.deepcopy(lock)
        del modified["packages"]["node_modules/@playwright/mcp"]["integrity"]
        with self.assertRaises(module.BadLock):
            module.validate(package, modified, version)

    def test_invalid_integrity_rejected(self):
        modified = copy.deepcopy(lock)
        modified["packages"]["node_modules/playwright"]["integrity"] = "sha512-AAAA"
        with self.assertRaises(module.BadLock):
            module.validate(package, modified, version)

    def test_mcp_transitive_version_change_rejected(self):
        modified = copy.deepcopy(lock)
        modified["packages"]["node_modules/playwright-core"]["version"] = "999.0.0"
        with self.assertRaises(module.BadLock):
            module.validate(package, modified, version)

    def test_wrong_tarball_host_rejected(self):
        modified = copy.deepcopy(lock)
        modified["packages"]["node_modules/playwright"]["resolved"] = (
            "https://example.invalid/playwright.tgz")
        with self.assertRaises(module.BadLock):
            module.validate(package, modified, version)

    def test_root_manifest_mismatch_rejected(self):
        modified = copy.deepcopy(package)
        modified["dependencies"]["@playwright/mcp"] = "latest"
        with self.assertRaises(module.BadLock):
            module.validate(modified, lock, version)

    def test_duplicate_version_key_rejected(self):
        with self.assertRaises(module.BadLock):
            module.checked_version("PLAYWRIGHT_MCP_VERSION=0.0.84\n"
                                   "PLAYWRIGHT_MCP_VERSION=0.0.85\n")


if __name__ == "__main__":
    unittest.main()
