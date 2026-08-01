#!/usr/bin/env python3
"""Tests for standalone artifact inspection pin validation."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).with_name("validate-standalone-artifact-inspection.py")


def load_validator() -> ModuleType:
    """Load the validator module."""
    spec = importlib.util.spec_from_file_location("artifact_inspection_validator", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENV = """\
CODEX_RELEASE_TAG=rust-v1.2.3
CODEX_AMD64_SHA256={codex_a}
CODEX_ARM64_SHA256={codex_b}
GH_VERSION=2.3.4
GH_AMD64_SHA256={gh_a}
GH_ARM64_SHA256={gh_b}
TTYD_VERSION=1.7.7
TTYD_AMD64_SHA256={ttyd_a}
TTYD_ARM64_SHA256={ttyd_b}
MISE_VERSION=2026.8.1
MISE_AMD64_SHA256={mise_a}
MISE_ARM64_SHA256={mise_b}
UV_VERSION=0.12.3
""".format(
    codex_a="a" * 64,
    codex_b="b" * 64,
    gh_a="c" * 64,
    gh_b="d" * 64,
    ttyd_a="e" * 64,
    ttyd_b="f" * 64,
    mise_a="1" * 64,
    mise_b="2" * 64,
)

LOCK = """\
[[tools.uv]]
version = "0.12.3"
backend = "aqua:astral-sh/uv"

[tools.uv."platforms.linux-arm64"]
checksum = "sha256:{arm}"
url = "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-aarch64-unknown-linux-musl.tar.gz"

[tools.uv."platforms.linux-x64"]
checksum = "sha256:{amd}"
url = "https://github.com/astral-sh/uv/releases/download/0.12.3/uv-x86_64-unknown-linux-musl.tar.gz"
""".format(arm="3" * 64, amd="4" * 64)


class ValidatorTests(unittest.TestCase):
    """Exercise current and stale report cases."""

    def setUp(self) -> None:
        self.validator = load_validator()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "third_party").mkdir()
        (self.root / "versions.env").write_text(ENV, encoding="utf-8")
        (self.root / "mise.lock").write_text(LOCK, encoding="utf-8")
        expected = self.validator.expected_report(
            self.validator.read_env(self.root / "versions.env"),
            self.root / "mise.lock",
        )
        self.report = {
            "schema_version": 1,
            "components": [
                {
                    "id": component_id,
                    "version": record["version"],
                    "architecture_legal_sets_equal": True,
                    "architectures": {
                        arch: {**asset, "asset_size": 123}
                        for arch, asset in record["architectures"].items()
                    },
                }
                for component_id, record in expected.items()
            ],
        }
        self.write_report(self.report)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_report(self, report: dict) -> None:
        """Write one report fixture."""
        (self.root / self.validator.REPORT_PATH).write_text(
            json.dumps(report),
            encoding="utf-8",
        )

    def test_current_report_passes(self) -> None:
        self.validator.validate(self.root)

    def test_stale_component_version_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["components"][0]["version"] = "old"
        self.write_report(report)
        with self.assertRaisesRegex(SystemExit, "inspection version is stale"):
            self.validator.validate(self.root)

    def test_stale_digest_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["components"][1]["architectures"]["amd64"]["asset_sha256"] = "0" * 64
        self.write_report(report)
        with self.assertRaisesRegex(SystemExit, "asset_sha256 is stale"):
            self.validator.validate(self.root)

    def test_uv_lock_change_fails(self) -> None:
        lock = LOCK.replace("4" * 64, "5" * 64)
        (self.root / "mise.lock").write_text(lock, encoding="utf-8")
        self.write_report(copy.deepcopy(self.report))
        with self.assertRaisesRegex(SystemExit, "uv amd64 asset_sha256 is stale"):
            self.validator.validate(self.root)

    def test_duplicate_component_fails(self) -> None:
        report = copy.deepcopy(self.report)
        report["components"].append(copy.deepcopy(report["components"][0]))
        self.write_report(report)
        with self.assertRaisesRegex(SystemExit, "duplicate standalone"):
            self.validator.validate(self.root)

    def test_missing_architecture_fails(self) -> None:
        report = copy.deepcopy(self.report)
        del report["components"][0]["architectures"]["arm64"]
        self.write_report(report)
        with self.assertRaisesRegex(SystemExit, "exactly amd64 and arm64"):
            self.validator.validate(self.root)


if __name__ == "__main__":
    unittest.main()
