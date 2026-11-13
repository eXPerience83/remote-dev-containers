#!/usr/bin/env python3
"""Fail-closed regression tests for shared standalone artifact validators."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

import standalone_artifact_common as common

SCRIPTS = Path(__file__).resolve().parent
REPOSITORIES = (
    ("yq", "mikefarah/yq", "raw-binary"),
    ("shfmt", "mvdan/sh", "raw-binary"),
    ("actionlint", "rhysd/actionlint", "tar.gz"),
)
VERSIONS = {name.upper() + "_VERSION": "1.2.3" for name, _, _ in REPOSITORIES}


def load_script(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def aqua_lock() -> str:
    records: list[str] = []
    for name, repo, _ in REPOSITORIES:
        records.extend((
            f"[[tools.{name}]]",
            'version = "1.2.3"',
            f'backend = "aqua:{repo}"',
        ))
        for arch, platform in (("amd64", "linux-x64"), ("arm64", "linux-arm64")):
            filename = {
                "yq": f"yq_linux_{arch}",
                "shfmt": f"shfmt_v1.2.3_linux_{arch}",
                "actionlint": f"actionlint_1.2.3_linux_{arch}.tar.gz",
            }[name]
            records.extend((
                f'[tools.{name}."platforms.{platform}"]',
                f'url = "https://github.com/{repo}/releases/download/v1.2.3/{filename}"',
                f'checksum = "sha256:{"7" * 64}"',
            ))
    return "\n".join(records) + "\n"


def uv_lock(url: str) -> str:
    lines = ['[[tools.uv]]', 'version = "0.12.3"']
    for arch, platform in (("amd64", "linux-x64"), ("arm64", "linux-arm64")):
        lines.extend((
            f'[tools.uv."platforms.{platform}"]',
            f'url = "{url}"',
            f'checksum = "sha256:{"a" * 64}"',
        ))
    return "\n".join(lines) + "\n"


class SharedStandaloneArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, filename: str, value: str) -> Path:
        path = self.root / filename
        path.write_text(value, encoding="utf-8")
        return path

    def test_both_consumers_use_the_same_helpers(self) -> None:
        for script in (
            "sync-standalone-artifact-inspection.py",
            "validate-standalone-artifact-inspection.py",
        ):
            with self.subTest(script=script):
                module = load_script(SCRIPTS / script, "shared_test_" + script[:4])
                for name in ("fail", "read_env", "load_report", "locked_validation_assets"):
                    self.assertIs(getattr(module, name), getattr(common, name))

    def test_read_env_ignores_comments_and_preserves_values(self) -> None:
        path = self.write("versions.env", "# comment\n\nFOO=one=two\nBAR=three\n")
        self.assertEqual(common.read_env(path), {"FOO": "one=two", "BAR": "three"})

    def test_read_env_rejects_invalid_inputs(self) -> None:
        examples = (
            ("KEY=one\nKEY=two\n", "duplicate environment key"),
            ("bad=lowercase\n", "invalid environment key"),
            ("NO_EQUALS\n", "invalid environment assignment"),
            ("KEY =value\n", "invalid environment key"),
        )
        for content, error in examples:
            with self.subTest(content=content):
                with self.assertRaisesRegex(SystemExit, error):
                    common.read_env(self.write("versions.env", content))
        with self.assertRaisesRegex(SystemExit, "cannot read"):
            common.read_env(self.root / "missing.env")

    def test_locked_aqua_assets_match_both_architectures(self) -> None:
        lock_path = self.write("mise.lock", aqua_lock())
        assets = common.locked_validation_assets(VERSIONS, lock_path)
        self.assertEqual(set(assets), {"yq", "shfmt", "actionlint"})
        self.assertEqual(set(assets["yq"]["architectures"]), {"amd64", "arm64"})
        self.assertEqual(assets["actionlint"]["packaging"], "tar.gz")
        self.assertEqual(assets["yq"]["architectures"]["amd64"]["asset_sha256"], "7" * 64)

    def test_locked_aqua_assets_reject_tampered_origin_digest_and_pins(self) -> None:
        source = aqua_lock()
        examples = (
            (source.replace("aqua:mikefarah/yq", "aqua:other/yq"), VERSIONS, "unreviewed locked yq"),
            (source.replace("sha256:" + "7" * 64, "sha256:" + "g" * 64, 1), VERSIONS, "unexpected yq amd64 artifact"),
            (source.replace("https://github.com/mikefarah/yq", "https://example.invalid/yq"),
             VERSIONS, "unexpected yq amd64 artifact"),
            (source, {**VERSIONS, "SHFMT_VERSION": "9.9.9"}, "unreviewed locked shfmt"),
            (source, {key: value for key, value in VERSIONS.items() if key != "YQ_VERSION"},
             "missing locked yq"),
        )
        for content, pins, error in examples:
            with self.subTest(error=error):
                with self.assertRaisesRegex(SystemExit, error):
                    common.locked_validation_assets(pins, self.write("mise.lock", content))

    def test_report_parser_rejects_invalid_schema_and_structure(self) -> None:
        good = {"schema_version": 1, "components": []}
        self.assertEqual(common.load_report(self.write("report.json", json.dumps(good))), good)
        examples = (
            ('{bad', "cannot read valid"),
            ('[]', "unsupported standalone artifact inspection report"),
            (json.dumps({"schema_version": 2, "components": []}), "unsupported"),
            (json.dumps({"schema_version": 1}), "no components array"),
            (json.dumps({"schema_version": 1, "components": {}}), "no components array"),
        )
        for content, error in examples:
            with self.subTest(content=content):
                with self.assertRaisesRegex(SystemExit, error):
                    common.load_report(self.write("report.json", content))

    def test_sync_uv_origin_policy_is_not_relaxed(self) -> None:
        sync = load_script(SCRIPTS / "sync-standalone-artifact-inspection.py", "sync_origin")
        official = "https://github.com/astral-sh/uv/releases/download/0.12.3/uv.tar.gz"
        self.assertEqual(
            set(sync.load_uv_assets(self.write("mise.lock", uv_lock(official)), "0.12.3")),
            {"amd64", "arm64"},
        )
        with self.assertRaisesRegex(SystemExit, "no trusted uv URL"):
            sync.load_uv_assets(
                self.write("mise.lock", uv_lock("https://example.invalid/uv.tar.gz")),
                "0.12.3",
            )


if __name__ == "__main__":
    unittest.main()
