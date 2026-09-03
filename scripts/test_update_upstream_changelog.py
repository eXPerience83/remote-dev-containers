#!/usr/bin/env python3
"""Regression tests for automated upstream changelog provenance."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "update-upstream-changelog.py"
SPEC = importlib.util.spec_from_file_location("update_upstream_changelog", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load update-upstream-changelog.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE_CHANGELOG = """# Changelog

## [Unreleased]

### Automated upstream refreshes

<!-- remote-dev-upstream-refreshes -->

### Added

- Human-authored entry.

## [0.0.1] - 2026-01-01
"""

BASE_VERSIONS = """CODEX_RELEASE_TAG=rust-v0.152.1
GH_VERSION=2.99.0
TTYD_VERSION=1.7.7
MISE_VERSION=2026.9.0
PYTHON_VERSION=3.14.7
NODE_VERSION=24.20.0
NPM_VERSION=12.0.2
UV_VERSION=0.12.9
CODEX_AMD64_SHA256=oldhash
"""


class UpstreamChangelogTests(unittest.TestCase):
    def test_multiple_version_changes_generate_one_exact_entry(self) -> None:
        before = MODULE.parse_versions(self._write("before.env", BASE_VERSIONS))
        after_text = BASE_VERSIONS.replace(
            "CODEX_RELEASE_TAG=rust-v0.152.1", "CODEX_RELEASE_TAG=rust-v0.153.0"
        ).replace("GH_VERSION=2.99.0", "GH_VERSION=2.100.0")
        after = MODULE.parse_versions(self._write("after.env", after_text))
        changes = MODULE.changed_components(before, after)
        updated = MODULE.update_changelog(BASE_CHANGELOG, "2026-09-03", changes)
        self.assertIn(
            "- 2026-09-03 — Codex CLI 0.152.1 → 0.153.0; GitHub CLI 2.99.0 → 2.100.0.",
            updated,
        )
        self.assertEqual(updated.count("2026-09-03 —"), 1)
        self.assertIn("- Human-authored entry.", updated)

    def test_single_change_lists_only_that_component(self) -> None:
        before = MODULE.parse_versions(self._write("before.env", BASE_VERSIONS))
        after = MODULE.parse_versions(
            self._write("after.env", BASE_VERSIONS.replace("UV_VERSION=0.12.9", "UV_VERSION=0.13.0"))
        )
        changes = MODULE.changed_components(before, after)
        self.assertEqual(changes, ["uv 0.12.9 → 0.13.0"])

    def test_hash_only_change_does_not_modify_changelog(self) -> None:
        before = MODULE.parse_versions(self._write("before.env", BASE_VERSIONS))
        after = MODULE.parse_versions(
            self._write("after.env", BASE_VERSIONS.replace("CODEX_AMD64_SHA256=oldhash", "CODEX_AMD64_SHA256=newhash"))
        )
        changes = MODULE.changed_components(before, after)
        self.assertEqual(changes, [])
        self.assertEqual(
            MODULE.update_changelog(BASE_CHANGELOG, "2026-09-03", changes),
            BASE_CHANGELOG,
        )

    def test_existing_generated_history_is_preserved(self) -> None:
        historical = BASE_CHANGELOG.replace(
            "<!-- remote-dev-upstream-refreshes -->",
            "<!-- remote-dev-upstream-refreshes -->\n\n- 2026-08-27 — uv 0.12.8 → 0.12.9.",
        )
        updated = MODULE.update_changelog(
            historical, "2026-09-03", ["npm 12.0.2 → 12.0.3"]
        )
        self.assertLess(updated.index("2026-09-03"), updated.index("2026-08-27"))
        self.assertIn("- Human-authored entry.", updated)

    def test_missing_marker_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "ownership marker"):
            MODULE.update_changelog(
                BASE_CHANGELOG.replace("<!-- remote-dev-upstream-refreshes -->", ""),
                "2026-09-03",
                ["uv 0.12.9 → 0.13.0"],
            )

    def _write(self, name: str, content: str) -> Path:
        if not hasattr(self, "_tempdir"):
            self._tempdir = tempfile.TemporaryDirectory()
            self.addCleanup(self._tempdir.cleanup)
        path = Path(self._tempdir.name) / name
        path.write_text(content, encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
