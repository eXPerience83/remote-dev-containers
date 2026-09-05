#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate-antigravity-project-boundary.py"


class AntigravityBoundaryValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="remote-dev-agy-boundary-")
        self.root = Path(self.tmp.name)
        self.project = self.root / "workspace" / "project"
        self.project.mkdir(parents=True)
        self.settings = self.root / "settings.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_settings(self, data: object) -> bytes:
        raw = (json.dumps(data, separators=(",", ":")) + "\n").encode()
        self.settings.write_bytes(raw)
        self.settings.chmod(0o600)
        return raw

    def run_validator(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                str(VALIDATOR),
                "--settings",
                str(self.settings),
                "--project",
                str(self.project),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    def assert_passes(self, data: object) -> None:
        before = self.write_settings(data)
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.settings.read_bytes(), before, "validator modified settings")

    def assert_blocks(self, data: object, text: str) -> None:
        before = self.write_settings(data)
        result = self.run_validator()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(text, result.stderr)
        self.assertEqual(self.settings.read_bytes(), before, "validator modified blocked settings")

    def safe_settings(self) -> dict[str, object]:
        return {
            "allowNonWorkspaceAccess": False,
            "permissions": {
                "allow": ["command(git status)", "write_file(src/)", "read_file(README.md)"],
                "ask": ["command(*)"],
                "deny": ["unsandboxed(*)"],
            },
            "unrelatedFutureSetting": {"preserve": True},
        }

    def test_safe_policy_passes_and_is_byte_preserving(self) -> None:
        self.assert_passes(self.safe_settings())

    def test_sandbox_setting_may_be_absent_or_boolean_because_launch_flag_owns_it(self) -> None:
        data = self.safe_settings()
        data["enableTerminalSandbox"] = False
        self.assert_passes(data)
        data["enableTerminalSandbox"] = True
        self.assert_passes(data)

    def test_non_workspace_access_enabled_or_malformed_is_blocked(self) -> None:
        data = self.safe_settings()
        data["allowNonWorkspaceAccess"] = True
        self.assert_blocks(data, "must be disabled")
        data["allowNonWorkspaceAccess"] = "false"
        self.assert_blocks(data, "must be boolean")

    def test_deny_all_unsandboxed_rule_is_required(self) -> None:
        data = self.safe_settings()
        data["permissions"]["deny"] = []  # type: ignore[index]
        self.assert_blocks(data, "must contain unsandboxed(*)")

    def test_unsandboxed_allow_is_rejected_even_with_deny_precedence(self) -> None:
        data = self.safe_settings()
        data["permissions"]["allow"].append("unsandboxed(git push)")  # type: ignore[index,union-attr]
        self.assert_blocks(data, "contains an unsandboxed grant")

    def test_relative_file_grants_inside_project_are_allowed(self) -> None:
        data = self.safe_settings()
        data["permissions"]["allow"] = [  # type: ignore[index]
            "read_file(docs/)",
            "write_file(src/pkg/)",
        ]
        self.assert_passes(data)

    def test_absolute_file_grant_is_allowed_only_inside_selected_project(self) -> None:
        data = self.safe_settings()
        data["permissions"]["allow"] = [  # type: ignore[index]
            f"write_file({self.project / 'src'})",
            f"read_file({self.project / 'docs'})",
        ]
        self.assert_passes(data)
        data["permissions"]["allow"] = [  # type: ignore[index]
            f"write_file({self.project.parent / 'sibling'})",
        ]
        self.assert_blocks(data, "outside the selected project")

    def test_global_parent_and_home_file_grants_are_blocked(self) -> None:
        for rule in ("read_file(*)", "write_file(../sibling)", "read_file(~/.ssh)", "write_file(/workspace)"):
            data = self.safe_settings()
            data["permissions"]["allow"] = [rule]  # type: ignore[index]
            self.assert_blocks(data, "outside the selected project")

    def test_permission_lists_and_safety_types_fail_closed(self) -> None:
        data = self.safe_settings()
        data["permissions"]["allow"] = "command(git)"  # type: ignore[index]
        self.assert_blocks(data, "must be a list of strings")
        data = self.safe_settings()
        data["enableTerminalSandbox"] = "true"
        self.assert_blocks(data, "must be boolean")

    def test_missing_settings_and_permissions_fail_closed(self) -> None:
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("settings are missing", result.stderr)
        self.assert_blocks({}, "permissions are missing")

    def test_symlink_broad_permissions_and_duplicate_keys_fail_closed(self) -> None:
        target = self.root / "target.json"
        target.write_text('{"permissions":{"deny":["unsandboxed(*)"]}}\n', encoding="utf-8")
        target.chmod(0o600)
        self.settings.symlink_to(target)
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be opened safely", result.stderr)
        self.settings.unlink()

        self.write_settings(self.safe_settings())
        self.settings.chmod(0o644)
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("permissions are too broad", result.stderr)

        self.settings.write_text(
            '{"allowNonWorkspaceAccess":false,"allowNonWorkspaceAccess":true,"permissions":{"deny":["unsandboxed(*)"]}}\n',
            encoding="utf-8",
        )
        self.settings.chmod(0o600)
        result = self.run_validator()
        self.assertEqual(result.returncode, 2)
        self.assertIn("duplicate keys", result.stderr)


if __name__ == "__main__":
    unittest.main()
