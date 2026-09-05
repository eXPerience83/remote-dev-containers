#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate-codex-project-boundary.py"


FAKE_CODEX = r'''#!/usr/bin/env python3
import json
import os
import sys

policy_name = os.environ.get("REMOTE_DEV_TEST_POLICY", "safe")
ceiling = os.environ.get("GIT_CEILING_DIRECTORIES", "")

for raw in sys.stdin:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        continue
    if message.get("method") == "initialize":
        print(json.dumps({"id": message.get("id"), "result": {}}), flush=True)
    elif message.get("method") == "initialized":
        continue
    elif message.get("method") == "config/read":
        policy = {
            "inherit": "all",
            "ignore_default_excludes": True,
            "exclude": [],
            "set": {"GIT_CEILING_DIRECTORIES": ceiling},
            "include_only": [],
        }
        if policy_name == "include_drop":
            policy["include_only"] = ["PATH", "HOME"]
        elif policy_name == "include_exact":
            policy["include_only"] = ["GIT_CEILING_DIRECTORIES"]
        elif policy_name == "include_wildcard":
            policy["include_only"] = ["GIT_*", "PATH"]
        elif policy_name == "wrong_set":
            policy["set"]["GIT_CEILING_DIRECTORIES"] = "/wrong"
        elif policy_name == "missing_policy":
            policy = None
        elif policy_name == "filter_drop":
            policy["filters"] = {"PATH": "include", "GIT_*": "exclude"}
        elif policy_name == "filter_include":
            policy["filters"] = {"GIT_*": "include"}
        elif policy_name == "unknown_filter":
            policy["filters"] = {"GIT_*": "maybe"}
        config = {} if policy is None else {"shell_environment_policy": policy}
        print(json.dumps({"id": message.get("id"), "result": {"config": config, "origins": {}}}), flush=True)
'''


class CodexProjectBoundaryValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="remote-dev-codex-boundary-")
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.project = self.workspace / "project"
        self.project.mkdir(parents=True)
        self.binary = self.root / "codex"
        self.binary.write_text(textwrap.dedent(FAKE_CODEX), encoding="utf-8")
        self.binary.chmod(0o755)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_validator(self, policy: str = "safe") -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["REMOTE_DEV_TEST_POLICY"] = policy
        return subprocess.run(
            [
                str(VALIDATOR),
                "--codex-binary",
                str(self.binary),
                "--cwd",
                str(self.project),
                "--ceiling",
                str(self.workspace),
            ],
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )

    def assert_passes(self, policy: str) -> None:
        result = self.run_validator(policy)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def assert_blocks(self, policy: str, text: str) -> None:
        result = self.run_validator(policy)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(text, result.stderr)
        self.assertNotIn(str(self.workspace / ".git"), result.stderr)

    def test_default_policy_keeps_managed_set_value(self) -> None:
        self.assert_passes("safe")

    def test_exact_and_wildcard_include_only_keep_ceiling(self) -> None:
        self.assert_passes("include_exact")
        self.assert_passes("include_wildcard")

    def test_include_only_without_ceiling_fails_closed(self) -> None:
        self.assert_blocks("include_drop", "filters out the required Git ceiling")

    def test_canonical_include_filter_is_supported(self) -> None:
        self.assert_passes("filter_include")

    def test_canonical_include_filter_without_ceiling_fails_closed(self) -> None:
        self.assert_blocks("filter_drop", "filters out the required Git ceiling")

    def test_wrong_or_missing_managed_value_fails_closed(self) -> None:
        self.assert_blocks("wrong_set", "does not own the required Git ceiling")
        self.assert_blocks("missing_policy", "effective shell environment policy is unavailable")

    def test_unknown_filter_action_fails_closed(self) -> None:
        self.assert_blocks("unknown_filter", "filter action is unknown")

    def test_symlinked_binary_is_rejected(self) -> None:
        link = self.root / "codex-link"
        link.symlink_to(self.binary)
        result = subprocess.run(
            [
                str(VALIDATOR),
                "--codex-binary",
                str(link),
                "--cwd",
                str(self.project),
                "--ceiling",
                str(self.workspace),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unavailable or unsafe", result.stderr)


if __name__ == "__main__":
    unittest.main()
