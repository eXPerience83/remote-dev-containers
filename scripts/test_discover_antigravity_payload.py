#!/usr/bin/env python3
"""Regression tests for static Antigravity payload discovery."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent
MODULE_PATH = ROOT / "discover-antigravity-payload.py"
SPEC = importlib.util.spec_from_file_location("discover_antigravity_payload", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load discover-antigravity-payload.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PAYLOAD = b"synthetic-antigravity-payload-do-not-execute"
VERSION = "1.2.3"
PAYLOAD_URL = (
    "https://storage.googleapis.com/antigravity-public/antigravity-cli/"
    f"{VERSION}-123456/linux-x64/cli_linux_x64.tar.gz"
)
INSTALLER_BYTES = (
    b"#!/bin/bash\n"
    b"# antigravity-cli-auto-updater-974169037036.us-central1.run.app\n"
    b"# /manifests/\n"
    b"# sha512\n"
)


class AntigravityPayloadDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.installer = root / "install.sh"
        self.manifest = root / "manifest.json"
        self.archive = root / "payload.tar.gz"
        self.installer.write_bytes(INSTALLER_BYTES)
        self._write_archive(PAYLOAD)
        self._write_manifest(hashlib.sha512(self.archive.read_bytes()).hexdigest())
        self.installer_sha = hashlib.sha256(INSTALLER_BYTES).hexdigest()

    def _write_archive(
        self,
        payload: bytes,
        *,
        member_name: str = "antigravity",
        symlink: bool = False,
    ) -> None:
        with tarfile.open(self.archive, "w:gz") as archive:
            member = tarfile.TarInfo(member_name)
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "elsewhere"
                member.size = 0
                archive.addfile(member)
            else:
                member.size = len(payload)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(payload))

    def _write_manifest(self, archive_sha512: str, *, payload_url: str = PAYLOAD_URL) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "version": VERSION,
                    "url": payload_url,
                    "sha512": archive_sha512,
                }
            ),
            encoding="utf-8",
        )

    def _discover(self) -> dict:
        return MODULE.discover(
            expected_installer_sha256=self.installer_sha,
            installer_fixture=self.installer,
            manifest_fixture=self.manifest,
            archive_fixture=self.archive,
        )

    def test_static_discovery_hashes_payload_without_process_execution(self) -> None:
        with mock.patch.object(
            MODULE.INSPECTOR,
            "run",
            side_effect=AssertionError("static discovery must not execute any process"),
        ):
            report = self._discover()
        MODULE.validate_report(
            report,
            expected_installer_sha256=self.installer_sha,
            allow_fixtures=True,
        )
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["payload"]["path"], ".local/bin/agy")
        self.assertEqual(report["payload"]["size"], len(PAYLOAD))
        self.assertEqual(report["payload"]["sha256"], hashlib.sha256(PAYLOAD).hexdigest())
        serialized = json.dumps(report, sort_keys=True)
        for forbidden in ("installation", "bash_syntax", "help", "stdout", "stderr"):
            self.assertNotIn(f'"{forbidden}"', serialized)

    def test_installer_network_policy_allows_only_canonical_url(self) -> None:
        self.assertTrue(MODULE.installer_url_policy(MODULE.INSPECTOR.OFFICIAL_INSTALLER_URL))
        self.assertFalse(MODULE.installer_url_policy("https://antigravity.google/docs"))
        self.assertFalse(MODULE.installer_url_policy("http://antigravity.google/cli/install.sh"))
        self.assertFalse(
            MODULE.installer_url_policy("https://antigravity.google/cli/install.sh?x=1")
        )

    def test_discovery_requires_exact_installer_hash(self) -> None:
        with self.assertRaisesRegex(MODULE.DiscoveryError, "explicitly admitted"):
            MODULE.discover(
                expected_installer_sha256="0" * 64,
                installer_fixture=self.installer,
                manifest_fixture=self.manifest,
                archive_fixture=self.archive,
            )

    def test_manifest_payload_host_is_fixed(self) -> None:
        self._write_manifest(
            hashlib.sha512(self.archive.read_bytes()).hexdigest(),
            payload_url="https://example.invalid/payload.tar.gz",
        )
        with self.assertRaisesRegex(MODULE.DiscoveryError, "payload URL"):
            self._discover()

    def test_archive_sha512_must_match_manifest(self) -> None:
        self._write_manifest("0" * 128)
        with self.assertRaisesRegex(MODULE.DiscoveryError, "SHA-512 differs"):
            self._discover()

    def test_archive_rejects_unexpected_regular_member(self) -> None:
        self._write_archive(PAYLOAD, member_name="unexpected")
        self._write_manifest(hashlib.sha512(self.archive.read_bytes()).hexdigest())
        with self.assertRaisesRegex(MODULE.DiscoveryError, "unexpected regular file"):
            self._discover()

    def test_archive_rejects_symlink_member(self) -> None:
        self._write_archive(b"", symlink=True)
        self._write_manifest(hashlib.sha512(self.archive.read_bytes()).hexdigest())
        with self.assertRaisesRegex(MODULE.DiscoveryError, "link/device"):
            self._discover()

    def test_archive_member_limit_is_enforced_incrementally(self) -> None:
        with tarfile.open(self.archive, "w:gz") as archive:
            for index in range(MODULE.MAX_ARCHIVE_MEMBERS):
                directory = tarfile.TarInfo(f"dir-{index}")
                directory.type = tarfile.DIRTYPE
                archive.addfile(directory)
            payload = tarfile.TarInfo("antigravity")
            payload.size = len(PAYLOAD)
            payload.mode = 0o755
            archive.addfile(payload, io.BytesIO(PAYLOAD))
        self._write_manifest(hashlib.sha512(self.archive.read_bytes()).hexdigest())
        with self.assertRaisesRegex(MODULE.DiscoveryError, "member count"):
            self._discover()

    def test_fixture_trio_is_required(self) -> None:
        with self.assertRaisesRegex(MODULE.DiscoveryError, "fixtures must provide"):
            MODULE.discover(
                expected_installer_sha256=self.installer_sha,
                installer_fixture=self.installer,
                manifest_fixture=None,
                archive_fixture=None,
            )

    def test_validation_rejects_wrong_admitted_installer(self) -> None:
        report = self._discover()
        with self.assertRaisesRegex(MODULE.DiscoveryError, "differs from the admitted"):
            MODULE.validate_report(
                report,
                expected_installer_sha256="f" * 64,
                allow_fixtures=True,
            )

    def test_validation_rejects_extra_nested_metadata(self) -> None:
        report = self._discover()
        bad = deepcopy(report)
        bad["installer"]["vendor_note"] = "unexpected"
        with self.assertRaisesRegex(MODULE.DiscoveryError, "installer metadata is malformed"):
            MODULE.validate_report(
                bad,
                expected_installer_sha256=self.installer_sha,
                allow_fixtures=True,
            )

    def test_written_report_round_trips_through_schema_validation(self) -> None:
        output = Path(self.temp.name) / "report.json"
        report = MODULE.write_report(
            output,
            expected_installer_sha256=self.installer_sha,
            installer_fixture=self.installer,
            manifest_fixture=self.manifest,
            archive_fixture=self.archive,
        )
        persisted = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(persisted, report)
        MODULE.validate_report(
            persisted,
            expected_installer_sha256=self.installer_sha,
            allow_fixtures=True,
        )


if __name__ == "__main__":
    unittest.main()
