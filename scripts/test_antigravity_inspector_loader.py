#!/usr/bin/env python3
"""The shared Antigravity inspector loader preserves fixed-path and fresh-module behavior."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import antigravity_inspector_loader as loader

ROOT = Path(__file__).resolve().parent
CONSUMERS = (
    "detect-antigravity-installer.py",
    "discover-antigravity-payload.py",
    "run-antigravity-inspection.py",
)


class AntigravityInspectorLoaderTests(unittest.TestCase):
    def test_loads_only_fixed_same_directory_inspector_as_fresh_module(self) -> None:
        first = loader.load_inspector()
        second = loader.load_inspector()
        self.assertIsNot(first, second)
        self.assertEqual(first.__name__, "antigravity_inspector")
        self.assertEqual(second.__name__, "antigravity_inspector")
        self.assertEqual(
            Path(first.__file__).resolve(),
            ROOT / "inspect-antigravity-cli.py",
        )
        self.assertEqual(first.OFFICIAL_INSTALLER_URL, second.OFFICIAL_INSTALLER_URL)
        self.assertTrue(callable(first.sha256_bytes))
        self.assertTrue(callable(second.parse_sha256))

    def test_rejects_unavailable_module_spec(self) -> None:
        with mock.patch.object(
            loader.importlib.util,
            "spec_from_file_location",
            return_value=None,
        ):
            with self.assertRaisesRegex(RuntimeError, "could not load inspect"):
                loader.load_inspector()

    def test_rejects_module_spec_without_loader(self) -> None:
        with mock.patch.object(
            loader.importlib.util,
            "spec_from_file_location",
            return_value=SimpleNamespace(loader=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "could not load inspect"):
                loader.load_inspector()

    def test_each_consumer_uses_exact_shared_loader_without_cache(self) -> None:
        for name in CONSUMERS:
            with self.subTest(consumer=name):
                source = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn(
                    "from antigravity_inspector_loader import load_inspector",
                    source,
                )
                self.assertEqual(source.count("INSPECTOR = load_inspector()"), 1)
                self.assertNotIn("spec_from_file_location(", source)
                self.assertNotIn("INSPECTOR_PATH", source)


if __name__ == "__main__":
    unittest.main()
