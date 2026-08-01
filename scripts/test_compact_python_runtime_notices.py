#!/usr/bin/env python3
"""Unit tests for compact Python runtime legal metadata."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


SCRIPT = Path(__file__).with_name("compact-python-runtime-notices.py")


def load_compactor() -> ModuleType:
    """Load the hyphenated compactor script as a module."""
    spec = importlib.util.spec_from_file_location("python_runtime_notice_compactor", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSynchronizer:
    """Minimal synchronizer contract used by deterministic unit tests."""

    @staticmethod
    def referenced_license_paths(metadata):
        paths = {metadata["license_path"]}
        for variants in metadata["build_info"]["extensions"].values():
            for variant in variants:
                paths.update(variant.get("license_paths", []))
        return paths


class CompactNoticeTests(unittest.TestCase):
    """Exercise normalization without downloading artifacts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.compact_module = load_compactor()

    def assert_rejected(self, callable_obj, *args) -> None:
        with self.assertRaises(SystemExit):
            callable_obj(*args)

    def sample_metadata(self) -> dict:
        return {
            "python_version": "3.14.6",
            "target_triple": "x86_64-unknown-linux-gnu",
            "license_path": "licenses/LICENSE.cpython.txt",
            "licenses": ["Python-2.0", "CNRI-Python", "Python-2.0"],
            "build_info": {
                "extensions": {
                    "_ssl": [
                        {
                            "licenses": ["OpenSSL", "Apache-2.0"],
                            "license_paths": [
                                "licenses/LICENSE.openssl-3.txt",
                                "licenses/LICENSE.openssl-1.1.txt",
                            ],
                        }
                    ],
                    "plain": [{}],
                }
            },
        }

    def test_build_legal_summary_retains_only_license_relationships(self) -> None:
        summary = self.compact_module.build_legal_summary(
            self.sample_metadata(), FakeSynchronizer
        )
        self.assertEqual(summary["schema_version"], 1)
        self.assertEqual(summary["python_version"], "3.14.6")
        self.assertEqual(
            summary["implementation_licenses"], ["CNRI-Python", "Python-2.0"]
        )
        self.assertEqual(list(summary["extensions"]), ["_ssl"])
        self.assertEqual(
            summary["referenced_license_paths"],
            [
                "licenses/LICENSE.cpython.txt",
                "licenses/LICENSE.openssl-1.1.txt",
                "licenses/LICENSE.openssl-3.txt",
            ],
        )

    def test_build_legal_summary_rejects_malformed_lists(self) -> None:
        metadata = self.sample_metadata()
        metadata["licenses"] = "Python-2.0"
        self.assert_rejected(
            self.compact_module.build_legal_summary, metadata, FakeSynchronizer
        )

    def test_compact_replaces_raw_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for arch in ("amd64", "arm64"):
                arch_root = output / arch
                arch_root.mkdir()
                metadata = self.sample_metadata()
                metadata["target_triple"] = (
                    "x86_64-unknown-linux-gnu"
                    if arch == "amd64"
                    else "aarch64-unknown-linux-gnu"
                )
                (arch_root / "PYTHON.json").write_text(
                    json.dumps(metadata), encoding="utf-8"
                )
            self.compact_module.compact(output, FakeSynchronizer)
            for arch in ("amd64", "arm64"):
                self.assertFalse((output / arch / "PYTHON.json").exists())
                compact_path = output / arch / "license-metadata.json"
                self.assertTrue(compact_path.is_file())
                compact = json.loads(compact_path.read_text(encoding="utf-8"))
                self.assertEqual(compact["schema_version"], 1)

    def test_compact_rejects_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "amd64").mkdir()
            (output / "arm64").mkdir()
            self.assert_rejected(
                self.compact_module.compact, output, FakeSynchronizer
            )


if __name__ == "__main__":
    unittest.main()
