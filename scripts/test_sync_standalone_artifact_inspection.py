#!/usr/bin/env python3
"""Unit tests for bounded standalone artifact inspection helpers."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = Path(__file__).with_name("sync-standalone-artifact-inspection.py")
SPEC = importlib.util.spec_from_file_location("standalone_sync", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.stream = io.BytesIO(data)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.stream.read(size)


class StandaloneInspectionTests(unittest.TestCase):
    def test_tar_legal_member_matches_repository_notice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive_path = root / "asset.tar.gz"
            license_data = b"example license\n"
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, data in (
                    ("bundle/tool", b"binary"),
                    ("bundle/LICENSE", license_data),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
            notices = [
                {
                    "path": "third_party/components/example/LICENSE",
                    "sha256": hashlib.sha256(license_data).hexdigest(),
                    "size": len(license_data),
                }
            ]
            result = MODULE.inspect_asset(archive_path, "tar.gz", notices)
            self.assertEqual(result["archive_member_count"], 2)
            self.assertEqual(len(result["legal_members"]), 1)
            self.assertEqual(
                result["legal_members"][0]["matches_repository_notice"],
                notices[0]["path"],
            )

    def test_raw_binary_has_no_archive_members(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tool"
            path.write_bytes(b"abc")
            result = MODULE.inspect_asset(path, "raw-binary", [])
            self.assertEqual(result["asset_size"], 3)
            self.assertIsNone(result["archive_member_count"])
            self.assertEqual(result["legal_members"], [])

    def test_public_download_never_sends_repository_tokens(self) -> None:
        payload = b"public release asset"
        expected_sha256 = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "asset"
            with mock.patch.dict(
                os.environ,
                {"GH_TOKEN": "repository-secret", "GITHUB_TOKEN": "repository-secret"},
            ), mock.patch.object(
                MODULE.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ) as urlopen:
                MODULE.download_verified(
                    "https://github.com/example/tool/releases/download/v1/tool.tar.gz",
                    expected_sha256,
                    destination,
                )
            request = urlopen.call_args.args[0]
            self.assertEqual(
                request.header_items(),
                [("User-agent", "remote-dev-containers-standalone-inspection")],
            )
            self.assertEqual(destination.read_bytes(), payload)

    def test_legal_set_ignores_architecture_parent_directory(self) -> None:
        amd64 = {
            "legal_members": [
                {"path": "tool-amd64/LICENSE", "sha256": "a" * 64, "size": 10}
            ]
        }
        arm64 = {
            "legal_members": [
                {"path": "tool-arm64/LICENSE", "sha256": "a" * 64, "size": 10}
            ]
        }
        self.assertEqual(
            MODULE.normalized_legal_set(amd64),
            MODULE.normalized_legal_set(arm64),
        )

    def test_component_refresh_detects_pin_drift(self) -> None:
        expected = {
            "version": "2.0.0",
            "packaging": "raw-binary",
            "architectures": {
                "amd64": {
                    "asset_url": "https://github.com/x/a",
                    "asset_sha256": "a" * 64,
                },
                "arm64": {
                    "asset_url": "https://github.com/x/b",
                    "asset_sha256": "b" * 64,
                },
            },
        }
        notices = [{"path": "LICENSE", "sha256": "c" * 64, "size": 1}]
        actual = {
            "version": "1.0.0",
            "packaging": "raw-binary",
            "repository_notices": notices,
            "architecture_legal_sets_equal": True,
            "architectures": {
                "amd64": {
                    **expected["architectures"]["amd64"],
                    "asset_size": 1,
                    "archive_member_count": None,
                    "legal_members": [],
                },
                "arm64": {
                    **expected["architectures"]["arm64"],
                    "asset_size": 1,
                    "archive_member_count": None,
                    "legal_members": [],
                },
            },
        }
        self.assertFalse(MODULE.component_is_current(actual, expected, notices))
        actual["version"] = "2.0.0"
        self.assertTrue(MODULE.component_is_current(actual, expected, notices))

    def test_markdown_is_deterministic(self) -> None:
        report = {
            "components": [
                {
                    "id": "uv",
                    "version": "0.12.1",
                    "packaging": "tar.gz",
                    "repository_notices": [
                        {"path": "third_party/components/uv/LICENSE-MIT"}
                    ],
                    "architectures": {
                        "amd64": {"legal_members": []},
                        "arm64": {"legal_members": []},
                    },
                }
            ]
        }
        text = MODULE.render_markdown(report)
        self.assertIn("| uv | `0.12.1` | tar.gz | None | LICENSE-MIT |", text)
        self.assertTrue(text.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
