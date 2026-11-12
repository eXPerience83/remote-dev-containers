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
PROBE_SOURCE = Path(__file__).with_name("browser-sandbox-runtime-probe.py")
probe_spec = importlib.util.spec_from_file_location("remote_dev_browser_runtime_probe", PROBE_SOURCE)
assert probe_spec is not None and probe_spec.loader is not None
probe = importlib.util.module_from_spec(probe_spec)
probe_spec.loader.exec_module(probe)
spec = importlib.util.spec_from_file_location("remote_dev_browser_sandbox", SOURCE)
assert spec is not None and spec.loader is not None
sandbox = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sandbox
spec.loader.exec_module(sandbox)


class BrowserIsolationContract(unittest.TestCase):
    def test_process_identity_keeps_zombies_until_reaped(self):
        # /proc/pid/stat field 2 may contain spaces; field 22 is starttime.
        line = "42 (chrome renderer) Z " + "0 " * 18 + "123456 " + "0"
        self.assertEqual(probe.parse_process_start_time(line), 123456)
        with self.assertRaises(RuntimeError):
            probe.parse_process_start_time("42 malformed")

    def test_process_start_time_distinguishes_missing_and_reused_pid(self):
        with mock.patch.object(probe.Path, "read_text", return_value=(
                "42 (chrome) Z " + "0 " * 18 + "555 0")):
            self.assertEqual(probe.process_start_time(42), 555)
        with mock.patch.object(probe.Path, "read_text",
                               side_effect=FileNotFoundError):
            self.assertIsNone(probe.process_start_time(42))

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
        with mock.patch.object(sandbox, "valid_scratch", return_value=True):
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
        with mock.patch.object(sandbox, "valid_scratch", return_value=True):
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

    def test_private_scratch_requires_canonical_child_and_expected_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (mock.patch.object(sandbox, "TMP_ROOT", tmp),
                  mock.patch.object(sandbox, "UID", os.getuid())):
                scratch = Path(tmp) / "remote-dev-browser-owned"
                scratch.mkdir(mode=0o700)
                self.assertTrue(sandbox.valid_scratch(str(scratch)))
                for invalid in (str(scratch) + "/../remote-dev-browser-owned",
                                str(scratch) + "/..",
                                str(scratch / "nested"),
                                str(Path(tmp) / "other-dir"),
                                str(Path(tmp) / "remote-dev-browser-missing")):
                    with self.subTest(invalid=invalid):
                        self.assertFalse(sandbox.valid_scratch(invalid))
                symlink = Path(tmp) / "remote-dev-browser-symlink"
                symlink.symlink_to(scratch, target_is_directory=True)
                self.assertFalse(sandbox.valid_scratch(str(symlink)))
                with mock.patch.object(sandbox, "UID", -1):
                    self.assertFalse(sandbox.valid_scratch(str(scratch)))

    def test_guardian_rejects_scratch_traversal_before_root_cleanup(self):
        with mock.patch.object(sandbox.os, "geteuid", return_value=0):
            self.assertEqual(
                sandbox.guardian(
                    -1, "/run/remote-dev-browser-/../../workspace"), 2)

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

    def test_live_guardian_reaper_does_not_consume_node_exit_status(self):
        # The guardian must never call waitpid on its main, still-running MCP.
        # It can reap any adopted, already-exited Chromium descendants.
        with (mock.patch.object(sandbox, "adopted_children",
                                return_value=[777, 888, 889]),
              mock.patch.object(sandbox.os, "waitpid",
                                side_effect=[(888, 0), (0, 0)]) as waiter):
            sandbox.reap_exited_browser_children(777)
        self.assertEqual(waiter.call_args_list, [
            mock.call(888, os.WNOHANG),
            mock.call(889, os.WNOHANG),
        ])

    def test_live_guardian_reaper_tolerates_concurrent_reap(self):
        with (mock.patch.object(sandbox, "adopted_children",
                                return_value=[777, 888]),
              mock.patch.object(sandbox.os, "waitpid",
                                side_effect=ChildProcessError)):
            sandbox.reap_exited_browser_children(777)

    @unittest.skipUnless(sys.platform == "linux" and hasattr(os, "fork"),
                         "requires Linux subreaper adoption")
    def test_live_guardian_reaper_collects_actual_orphaned_zombie(self):
        # Isolated Python subprocess: never change the unittest runner's
        # subreaper state, and never touch other running MCPs.
        fixture = r"""
import ctypes
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

spec = importlib.util.spec_from_file_location("sandbox_reaper_fixture", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
assert ctypes.CDLL(None, use_errno=True).prctl(
    mod.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
node = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(8)"])
try:
    maker = subprocess.Popen(
        [sys.executable, "-c",
         "import os; pid=os.fork(); "
         "os._exit(0) if pid == 0 else print(pid, flush=True)"],
        stdout=subprocess.PIPE, text=True)
    assert maker.stdout is not None
    zombie = int(maker.stdout.readline().strip())
    maker.stdout.close()
    maker.wait(timeout=3)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            stat = Path(f"/proc/{zombie}/stat").read_text()
        except FileNotFoundError:
            stat = ""
        # Expected zombie, adopted by this isolated subreaper.
        if stat and stat.rsplit(")", 1)[1].split()[:2] == ["Z", str(os.getpid())]:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("fixture failed to create an adopted zombie")
    assert node.poll() is None, "MCP stand-in exited too early"
    mod.reap_exited_browser_children(node.pid)
    assert not Path(f"/proc/{zombie}").exists(), "adopted zombie remained"
    assert node.poll() is None, "reaper disrupted still-running MCP"
finally:
    node.terminate()
    node.wait(timeout=3)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-c", fixture, str(SOURCE)],
            capture_output=True, text=True, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_supervisor_is_subreaper_before_spawning_guardian(self):
        with (mock.patch.object(sandbox.libc, "prctl", return_value=0) as ctl,
              mock.patch.object(sandbox, "adopted_children",
                                return_value=[]) as children):
            sandbox.supervisor_runtime_hardening()
        ctl.assert_called_once_with(sandbox.PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
        children.assert_called_once()

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
