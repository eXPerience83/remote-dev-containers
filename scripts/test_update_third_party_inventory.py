#!/usr/bin/env python3
"""Unit tests for the bounded third-party inventory updater."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


SCRIPT = Path(__file__).with_name("update-third-party-inventory.py")


def load_updater() -> ModuleType:
    """Load the updater script without requiring a package rename."""
    spec = importlib.util.spec_from_file_location("third_party_inventory_updater", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpdaterContractTests(unittest.TestCase):
    """Exercise deterministic validation without network access."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.updater = load_updater()

    def assert_rejected(self, callable_obj, *args) -> None:
        with self.assertRaises(SystemExit):
            callable_obj(*args)

    def test_parse_versions_accepts_comments_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versions.env"
            path.write_text("# comment\nFOO=1.2.3\nBAR=value=with=equals\n", encoding="utf-8")
            self.assertEqual(
                self.updater.parse_versions(path),
                {"FOO": "1.2.3", "BAR": "value=with=equals"},
            )

    def test_parse_versions_rejects_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versions.env"
            path.write_text("BROKEN\n", encoding="utf-8")
            self.assert_rejected(self.updater.parse_versions, path)

    def test_notice_url_requires_approved_https_host(self) -> None:
        valid = "https://raw.githubusercontent.com/cli/cli/v2.97.0/LICENSE"
        self.updater.validate_notice_url(valid, "2.97.0")
        self.assert_rejected(
            self.updater.validate_notice_url,
            "http://raw.githubusercontent.com/cli/cli/v2.97.0/LICENSE",
            "2.97.0",
        )
        self.assert_rejected(
            self.updater.validate_notice_url,
            "https://user:secret@raw.githubusercontent.com/cli/cli/v2.97.0/LICENSE",
            "2.97.0",
        )
        self.assert_rejected(
            self.updater.validate_notice_url,
            "https://example.com/cli/cli/v2.97.0/LICENSE",
            "2.97.0",
        )

    def test_notice_url_requires_exactly_one_version_token(self) -> None:
        self.assert_rejected(
            self.updater.validate_notice_url,
            "https://raw.githubusercontent.com/cli/cli/main/LICENSE",
            "2.97.0",
        )
        self.assert_rejected(
            self.updater.validate_notice_url,
            "https://raw.githubusercontent.com/cli/cli/v2.97.0/LICENSE?old=2.97.0",
            "2.97.0",
        )

    def test_derive_notice_url_replaces_one_reviewed_version(self) -> None:
        old = "https://raw.githubusercontent.com/jdx/mise/v2026.7.17/LICENSE"
        expected = "https://raw.githubusercontent.com/jdx/mise/v2026.7.18/LICENSE"
        self.assertEqual(
            self.updater.derive_notice_url(old, "2026.7.17", "2026.7.18"),
            expected,
        )

    def test_resolve_notice_path_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "third_party").mkdir()
            inside = self.updater.resolve_notice_path(
                root, "components/tool/LICENSE", "tool"
            )
            self.assertEqual(inside, root / "third_party/components/tool/LICENSE")
            self.assert_rejected(
                self.updater.resolve_notice_path,
                root,
                "../outside.txt",
                "tool",
            )

    def test_update_rejects_duplicate_keys_before_downloads(self) -> None:
        inventory = {
            "components": [
                {"id": "one", "version_key": "TOOL_VERSION", "version": "1", "notices": []},
                {"id": "two", "version_key": "TOOL_VERSION", "version": "1", "notices": []},
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            self.assert_rejected(
                self.updater.update_inventory,
                Path(directory),
                inventory,
                {"TOOL_VERSION": "1"},
            )


if __name__ == "__main__":
    unittest.main()
