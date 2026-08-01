#!/usr/bin/env python3
"""Unit tests for the bounded Python runtime notice synchronizer."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


SCRIPT = Path(__file__).with_name("sync-python-runtime-notices.py")


def load_synchronizer() -> ModuleType:
    """Load the hyphenated synchronizer script as a module."""
    spec = importlib.util.spec_from_file_location("python_runtime_notice_sync", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PythonRuntimeNoticeTests(unittest.TestCase):
    """Exercise deterministic behavior without network access."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.sync = load_synchronizer()

    def assert_rejected(self, callable_obj, *args) -> None:
        with self.assertRaises(SystemExit):
            callable_obj(*args)

    def test_parse_install_artifacts_requires_both_architectures(self) -> None:
        lock = """
[[tools.python]]
version = "3.14.6"
[tools.python."platforms.linux-arm64"]
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.14.6+20260728-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"
[tools.python."platforms.linux-x64"]
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.14.6+20260728-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mise.lock"
            path.write_text(lock, encoding="utf-8")
            records = self.sync.parse_install_artifacts(path)
        self.assertEqual([record["arch"] for record in records], ["amd64", "arm64"])
        self.assertEqual({record["release"] for record in records}, {"20260728"})
        self.assertEqual({record["python_version"] for record in records}, {"3.14.6"})

    def test_parse_install_artifacts_rejects_one_architecture(self) -> None:
        lock = """
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.14.6+20260728-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mise.lock"
            path.write_text(lock, encoding="utf-8")
            self.assert_rejected(self.sync.parse_install_artifacts, path)

    def test_select_full_asset_uses_upstream_preference(self) -> None:
        record = {
            "arch": "amd64",
            "target": "x86_64-unknown-linux-gnu",
            "python_version": "3.14.6",
            "release": "20260728",
        }
        prefix = "cpython-3.14.6+20260728-x86_64-unknown-linux-gnu-"
        assets = {
            f"{prefix}noopt-full.tar.zst": {"name": "noopt"},
            f"{prefix}pgo-full.tar.zst": {"name": "pgo"},
            f"{prefix}pgo+lto-full.tar.zst": {"name": "pgo+lto"},
        }
        selected = self.sync.select_full_asset(record, assets)
        self.assertEqual(selected["name"], "pgo+lto")

    def test_referenced_license_paths_walks_nested_metadata(self) -> None:
        metadata = {
            "python_implementation": {"license_path": "licenses/LICENSE.cpython.txt"},
            "extension_modules": {
                "_ssl": {
                    "license_paths": [
                        "licenses/LICENSE.openssl-3.txt",
                        "licenses/LICENSE.zlib.txt",
                    ]
                }
            },
        }
        self.assertEqual(
            self.sync.referenced_license_paths(metadata),
            {
                "licenses/LICENSE.cpython.txt",
                "licenses/LICENSE.openssl-3.txt",
                "licenses/LICENSE.zlib.txt",
            },
        )

    def test_referenced_license_paths_rejects_escape(self) -> None:
        self.assert_rejected(
            self.sync.referenced_license_paths,
            {"license_path": "../outside/LICENSE"},
        )

    def test_compare_license_trees_requires_equal_files_and_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first"
            second = root / "second"
            first.mkdir()
            second.mkdir()
            (first / "LICENSE").write_text("same\n", encoding="utf-8")
            (second / "LICENSE").write_text("same\n", encoding="utf-8")
            self.sync.compare_license_trees(first, second)
            (second / "LICENSE").write_text("different\n", encoding="utf-8")
            self.assert_rejected(self.sync.compare_license_trees, first, second)

    def test_check_accepts_metadata_tied_to_current_lock(self) -> None:
        lock = """
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.14.6+20260728-aarch64-unknown-linux-gnu-install_only_stripped.tar.gz"
url = "https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.14.6+20260728-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "third_party/components/python-build-standalone"
            licenses = output / "licenses"
            licenses.mkdir(parents=True)
            (licenses / "LICENSE.cpython.txt").write_text("license\n", encoding="utf-8")
            for arch in ("amd64", "arm64"):
                arch_root = output / arch
                arch_root.mkdir()
                (arch_root / "PYTHON.json").write_text(
                    json.dumps({"license_path": "licenses/LICENSE.cpython.txt"}),
                    encoding="utf-8",
                )
            (root / "mise.lock").write_text(lock, encoding="utf-8")
            records = self.sync.parse_install_artifacts(root / "mise.lock")
            manifest = {
                "schema_version": 1,
                "shared_license_texts": True,
                "supplemental_licenses": [
                    {
                        "source_url": entry["url"],
                        "sha256": entry["sha256"],
                    }
                    for entry in self.sync.SUPPLEMENTAL_LICENSES.values()
                ],
                "artifacts": [
                    {
                        **record,
                        "full_asset_sha256": "0" * 64,
                    }
                    for record in records
                ],
            }
            (output / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            self.sync.check(root, output)


if __name__ == "__main__":
    unittest.main()
