#!/usr/bin/env python3
"""Offline security contract tests for the isolated browser supervisor."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SOURCE = Path(__file__).with_name("remote-dev-browser-sandbox.py")
spec = importlib.util.spec_from_file_location("remote_dev_browser_sandbox", SOURCE)
assert spec is not None and spec.loader is not None
sandbox = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sandbox
spec.loader.exec_module(sandbox)


class BrowserIsolationContract(unittest.TestCase):
    def test_environment_allowlist_excludes_agent_secrets(self):
        scratch = "/run/remote-dev-browser-fixture"
        with mock.patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic-openai-key",
            "GITHUB_TOKEN": "synthetic-github-token",
            "GOOGLE_API_KEY": "synthetic-google-key",
            "LD_PRELOAD": "/workspace/evil.so",
            "NODE_OPTIONS": "--require=/workspace/evil.js",
            "HTTP_PROXY": "http://synthetic:secret@localhost:8080",
            "HTTPS_PROXY": "http://synthetic:secret@localhost:8080",
            "TMPDIR": "/workspace/.remote-dev-tmp/tmp",
            "BASH_ENV": "/workspace/evil",
        }):
            env = sandbox.safe_env(scratch)
        for key in ("OPENAI_API_KEY", "GITHUB_TOKEN", "GOOGLE_API_KEY",
                    "LD_PRELOAD", "NODE_OPTIONS", "HTTP_PROXY",
                    "HTTPS_PROXY", "BASH_ENV"):
            self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], scratch)
        self.assertEqual(env["TMPDIR"], scratch)
        self.assertEqual(env["XDG_RUNTIME_DIR"], scratch + "/runtime")
        self.assertEqual(env["PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD"], "1")
        self.assertEqual(env["PLAYWRIGHT_MCP_OUTPUT_DIR"], scratch + "/output")
        self.assertTrue(all("/workspace" not in v and "/root/" not in v
                            for v in env.values()))

    def test_filesystem_allowlist_never_grants_workspace_or_agent_state(self):
        node = "/opt/remote-dev/mise/installs/node/24.22.2/bin/node"
        rules = sandbox.rules(node, "/run/remote-dev-browser-fixture")
        allowed = [entry[0] for entry in rules]
        self.assertIn("/opt/remote-dev/playwright", allowed)
        self.assertIn("/opt/remote-dev/playwright-browsers", allowed)
        self.assertIn("/run/remote-dev-browser-fixture", allowed)
        self.assertNotIn("/workspace", allowed)
        self.assertNotIn("/root", allowed)
        proc_rights = dict(rules)["/proc"]
        self.assertFalse(proc_rights & sandbox.READ)
        self.assertTrue(proc_rights & sandbox.READDIR)
        self.assertIn("/proc/self", allowed)
        self.assertIn("/proc/cpuinfo", allowed)
        self.assertFalse(any(path.startswith("/root/") or
                             path.startswith("/workspace/") for path in allowed))
        self.assertFalse(sandbox.READ_ONLY & sandbox.WRITE)
        self.assertFalse(sandbox.WRITE_DIR & sandbox.EXEC)

    def test_rejects_untrusted_paths(self):
        with self.assertRaises(sandbox.IsolationError):
            sandbox.rules("/workspace/node", "/run/remote-dev-browser-fixture")
        with self.assertRaises(sandbox.IsolationError):
            sandbox.rules("/usr/bin/node", "/run/remote-dev-browser-fixture")
        with self.assertRaises(sandbox.IsolationError):
            sandbox.rules("/opt/remote-dev/mise/installs/node/24/bin/node",
                          "/workspace/not-private")
        with self.assertRaises(sandbox.IsolationError):
            sandbox.rules("/opt/remote-dev/mise/installs/node/24/bin/node",
                          "/tmp/not-private")

    def test_permissions_and_role_fail_closed(self):
        self.assertNotEqual(sandbox.UID, 0)
        self.assertEqual(sandbox.UID, sandbox.GID)
        self.assertEqual(sandbox.HANDLED, 0xffff)
        with mock.patch.object(sandbox.os, "geteuid", return_value=1000):
            with self.assertRaises(sandbox.IsolationError):
                sandbox.supervise()
        with mock.patch.dict(os.environ, {"REMOTE_DEV_ROLE": "launcher"}):
            with mock.patch.object(sandbox.os, "geteuid", return_value=0):
                with self.assertRaises(sandbox.IsolationError):
                    sandbox.supervise()

    def test_guardian_reaps_detached_browser_process_groups(self):
        class NodeProcess:
            pid = 777

            def wait(self, timeout):
                return 0

        # A detached Chromium child is adopted by the guardian/subreaper
        # after Node exits. It must be killed even though it is not in
        # Node's own process group.
        with (mock.patch.object(sandbox, "adopted_children",
                                side_effect=[[888], []]) as adopted,
              mock.patch.object(sandbox, "kill_group") as killer,
              mock.patch.object(sandbox.os, "getpgid", return_value=888),
              mock.patch.object(sandbox.os, "getpgrp", return_value=42),
              mock.patch.object(sandbox.os, "waitpid", return_value=(0, 0)),
              mock.patch.object(sandbox.time, "sleep")):
            sandbox.cleanup_browser_tree(NodeProcess())
        self.assertEqual(adopted.call_count, 2)
        self.assertEqual(killer.call_args_list,
                         [mock.call(777), mock.call(888)])

    def test_subreaper_and_nondumpable_constants(self):
        self.assertEqual(sandbox.PR_SET_CHILD_SUBREAPER, 36)
        self.assertEqual(sandbox.PR_SET_DUMPABLE, 4)

    def test_browser_identity_cannot_run_cleanup_guardian(self):
        with mock.patch.object(sandbox.os, "geteuid", return_value=sandbox.UID):
            self.assertEqual(sandbox.guardian(-1, "/run/remote-dev-browser-fixture"), 2)

    def test_guardian_has_non_dumpable_policy(self):
        with (mock.patch.object(sandbox, "no_new_privileges") as nnp,
              mock.patch.object(sandbox.libc, "prctl", return_value=0) as ctl):
            sandbox.guardian_runtime_hardening()
        nnp.assert_called_once_with()
        self.assertEqual(ctl.call_args_list, [
            mock.call(sandbox.PR_SET_DUMPABLE, 0, 0, 0, 0),
            mock.call(sandbox.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0),
        ])

    def test_no_user_supplied_mcp_flags(self):
        proc = subprocess.run(
            [sys.executable, "-I", str(SOURCE), "--no-sandbox"],
            check=False, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("does not accept caller options", proc.stderr)

    def test_landlock_uses_real_fd_rules_and_enforcement(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_file = Path(tmp) / "file"
            fake_file.write_bytes(b"x")
            calls = []
            fd = os.open("/dev/null", os.O_RDONLY)
            def fake_syscall(number, *args):
                calls.append(number)
                if number == sandbox.LL_CREATE:
                    return fd
                return 0
            with (mock.patch.object(sandbox, "landlock_abi", return_value=7),
                  mock.patch.object(sandbox, "rules", return_value=[
                      (tmp, sandbox.WRITE_DIR),
                      (str(fake_file), sandbox.READ_ONLY)]),
                  mock.patch.object(sandbox, "syscall", side_effect=fake_syscall)):
                sandbox.landlock("/opt/remote-dev/mise/installs/node/24/bin/node", tmp)
            self.assertEqual(calls.count(sandbox.LL_CREATE), 1)
            self.assertEqual(calls.count(sandbox.LL_ADD), 2)
            self.assertEqual(calls.count(sandbox.LL_RESTRICT), 1)
            with self.assertRaises(OSError):
                os.fstat(fd)  # The ruleset descriptor must have been closed.

    def test_landlock_missing_must_fail(self):
        with mock.patch.object(sandbox, "landlock_abi", return_value=0):
            with self.assertRaises(sandbox.IsolationError):
                sandbox.landlock("/opt/remote-dev/mise/installs/node/24/bin/node",
                                 "/run/remote-dev-browser-fixture")


if __name__ == "__main__":
    unittest.main()
