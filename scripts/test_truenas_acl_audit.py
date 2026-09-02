#!/usr/bin/env python3
"""Regression tests for the read-only TrueNAS ACL audit."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("truenas-acl-audit.py")
SPEC = importlib.util.spec_from_file_location("truenas_acl_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def completed(command: list[str], stdout: str = "", stderr: str = "", code: int = 0):
    return subprocess.CompletedProcess(command, code, stdout=stdout, stderr=stderr)


def posix_acl(*, trivial: bool = True, uid: int = 0) -> dict[str, object]:
    return {
        "path": "/synthetic",
        "user": None,
        "group": None,
        "uid": uid,
        "gid": 0,
        "acltype": "POSIX1E",
        "acl": [
            {
                "tag": "USER_OBJ",
                "perms": {"READ": True, "WRITE": True, "EXECUTE": True},
                "default": False,
                "id": -1,
                "who": None,
            },
            {
                "tag": "GROUP_OBJ",
                "perms": {"READ": False, "WRITE": False, "EXECUTE": False},
                "default": False,
                "id": -1,
                "who": None,
            },
            {
                "tag": "OTHER",
                "perms": {"READ": False, "WRITE": False, "EXECUTE": False},
                "default": False,
                "id": -1,
                "who": None,
            },
        ],
        "trivial": trivial,
    }


class TrueNasAclAuditTests(unittest.TestCase):
    def make_root(
        self, *, include_antigravity: bool = False
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name) / "remote-dev"
        root.mkdir(mode=0o755)
        for spec in MODULE.directory_specs(include_antigravity=include_antigravity):
            path = root / spec.suffix
            path.mkdir(parents=True, exist_ok=True)
            os.chmod(path, spec.mode)
        return temp, root

    def fake_runner(
        self,
        root: Path,
        *,
        acltype: str = "posix",
        aclmode: str = "discard",
        acl_payload: dict[str, object] | None = None,
    ):
        payload = acl_payload or posix_acl()

        def run(command: list[str]):
            if command[:2] == ["zfs", "list"]:
                return completed(command, f"Pool1/remote-dev\t{root}\n")
            if command[:2] == ["zfs", "get"]:
                return completed(command, f"acltype\t{acltype}\naclmode\t{aclmode}\n")
            if command[:3] == ["midclt", "call", "filesystem.getacl"]:
                return completed(command, json.dumps(payload))
            raise AssertionError(f"unexpected command: {command}")

        return run

    def test_generic_posix_private_state_passes(self):
        temp, root = self.make_root()
        self.addCleanup(temp.cleanup)
        with mock.patch.object(MODULE, "run_command", side_effect=self.fake_runner(root)):
            info, findings = MODULE.audit(root, include_antigravity=False)
        self.assertEqual(findings, [])
        self.assertIn("Dataset Pool1/remote-dev: acltype=posix aclmode=discard", info)
        self.assertEqual(sum(line.startswith("Private state OK:") for line in info), 5)
        self.assertTrue(all("root-owned" in line for line in info if line.startswith("Private state OK:")))

    def test_antigravity_private_state_uses_shared_contract(self):
        temp, root = self.make_root(include_antigravity=True)
        self.addCleanup(temp.cleanup)
        with mock.patch.object(MODULE, "run_command", side_effect=self.fake_runner(root)):
            info, findings = MODULE.audit(root, include_antigravity=True)
        self.assertEqual(findings, [])
        self.assertEqual(sum(line.startswith("Private state OK:") for line in info), 12)
        self.assertTrue(
            any("state/antigravity/config" in line for line in info),
            msg="Antigravity config must be included in the private ACL audit",
        )

    def test_nfsv4_root_and_effective_acl_are_reported(self):
        temp, root = self.make_root()
        self.addCleanup(temp.cleanup)
        nfsv4 = {
            "path": "/synthetic",
            "uid": 0,
            "gid": 0,
            "acltype": "NFS4",
            "trivial": False,
            "acl": [
                {
                    "tag": "GROUP",
                    "perms": {"READ_DATA": True, "WRITE_DATA": True},
                    "default": False,
                    "id": 568,
                    "who": "apps",
                }
            ],
        }
        with mock.patch.object(
            MODULE,
            "run_command",
            side_effect=self.fake_runner(
                root,
                acltype="nfsv4",
                aclmode="passthrough",
                acl_payload=nfsv4,
            ),
        ):
            _info, findings = MODULE.audit(root, include_antigravity=False)
        messages = "\n".join(finding.message for finding in findings)
        self.assertIn("uses acltype=nfsv4", messages)
        self.assertIn("uses aclmode=passthrough", messages)
        self.assertIn("effective ACL type is 'NFS4'", messages)
        self.assertIn("effective POSIX ACL is not trivial", messages)
        self.assertIn("unexpected effective ACL entry", messages)

    def test_broad_mode_and_extended_posix_acl_are_reported(self):
        temp, root = self.make_root()
        self.addCleanup(temp.cleanup)
        os.chmod(root / "state/codex/agent", 0o750)
        extended = posix_acl(trivial=False)
        extended_acl = list(extended["acl"])
        extended_acl.append(
            {
                "tag": "USER",
                "perms": {"READ": True, "WRITE": False, "EXECUTE": True},
                "default": False,
                "id": 1000,
                "who": None,
            }
        )
        extended["acl"] = extended_acl
        with mock.patch.object(
            MODULE,
            "run_command",
            side_effect=self.fake_runner(root, acl_payload=extended),
        ):
            _info, findings = MODULE.audit(root, include_antigravity=False)
        messages = "\n".join(finding.message for finding in findings)
        self.assertIn("mode is 0750, expected 0700", messages)
        self.assertIn("effective POSIX ACL is not trivial", messages)
        self.assertIn("unexpected effective ACL entry: 'USER'", messages)

    def test_non_root_private_owner_is_reported(self):
        temp, root = self.make_root()
        self.addCleanup(temp.cleanup)
        with mock.patch.object(
            MODULE,
            "run_command",
            side_effect=self.fake_runner(root, acl_payload=posix_acl(uid=1000)),
        ):
            _info, findings = MODULE.audit(root, include_antigravity=False)
        messages = "\n".join(finding.message for finding in findings)
        self.assertIn("owner uid is 1000, expected root (0)", messages)


if __name__ == "__main__":
    unittest.main()
