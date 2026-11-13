#!/usr/bin/env python3
"""Offline acceptance of Antigravity Context7 reinstall and safety boundaries."""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

SRC = Path(__file__).with_name("remote-dev-context7-antigravity.py")
spec = importlib.util.spec_from_file_location("_antigravity_context7", SRC)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class Context7Antigravity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="context7-antigravity-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.configdir = self.root / "global"
        self.configdir.mkdir(mode=0o700)
        self.file = self.configdir / "mcp_config.json"
        self.backup = self.configdir / manager.BACKUP_FILE
        self.previous_role = os.environ.get("REMOTE_DEV_ROLE")
        os.environ["REMOTE_DEV_ROLE"] = "antigravity"
        self.addCleanup(self.restore_role)

    def restore_role(self):
        if self.previous_role is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = self.previous_role

    def call(self, *args):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = manager.main(list(args), directory=self.configdir)
        return result, stdout.getvalue(), stderr.getvalue()

    def test_missing_installs_without_other_changes(self):
        self.assertEqual(self.call("status", "--menu")[0], 0)
        self.assertFalse(self.file.exists())
        self.assertEqual(self.call("plan")[0], 0)
        self.assertFalse(self.file.exists())
        self.assertEqual(self.call("reinstall")[0], 2)
        self.assertFalse(self.file.exists())

        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        doc = json.loads(self.file.read_bytes())
        self.assertEqual(doc, {"mcpServers": {"context7": manager.ENTRY}})
        self.assertEqual(self.call("status", "--menu")[0], 0)
        self.assertEqual(self.call("plan")[0], 0)
        self.assertFalse(self.backup.exists())
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        saved = self.file.read_bytes()
        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        self.assertEqual(saved, self.file.read_bytes())

    def test_reinstall_is_scoped_and_backed_up(self):
        other = {"command": "/usr/local/bin/remote-dev-playwright-mcp", "timeoutSeconds": 90}
        doc = {
            "mcpServers": {"playwright": other, "context7": {"serverUrl": "https://wrong.example/mcp"},
                           "openaiDeveloperDocs": {"serverUrl": "https://example.invalid/docs"}},
            "preferences": {"custom": [1, "user-owned"]},
        }
        original = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode()
        self.file.write_bytes(original)
        code, text, _ = self.call("plan")
        self.assertEqual(code, 0)
        self.assertIn("REINSTALLABLE", text)
        self.assertEqual(self.file.read_bytes(), original)
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.call("status", "--menu")[0], 3)
        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        new = json.loads(self.file.read_bytes())
        self.assertEqual(new["mcpServers"]["context7"], manager.ENTRY)
        self.assertEqual(new["mcpServers"]["playwright"], other)
        self.assertEqual(new["mcpServers"]["openaiDeveloperDocs"], doc["mcpServers"]["openaiDeveloperDocs"])
        self.assertEqual(new["preferences"], doc["preferences"])
        self.assertEqual(self.backup.read_bytes(), original)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o600)
        again = self.file.read_bytes()
        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        self.assertEqual(again, self.file.read_bytes())


    def test_second_reinstall_keeps_previous_backup(self):
        first = b'{"mcpServers":{"context7":{"serverUrl":"https://first.example/mcp"}}}'
        second = b'{"mcpServers":{"context7":{"serverUrl":"https://second.example/mcp"}}}'
        self.file.write_bytes(first)
        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        self.assertEqual(self.backup.read_bytes(), first)
        self.file.write_bytes(second)
        self.assertEqual(self.call("reinstall", "--yes")[0], 0)
        history = list(self.configdir.glob(manager.BACKUP_FILE + ".*"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].read_bytes(), second)
        self.assertEqual(self.backup.read_bytes(), first)
        self.assertEqual(stat.S_IMODE(history[0].stat().st_mode), 0o600)

    def test_custom_auth_is_never_discarded(self):
        for name, entry in [
            ("header", {"serverUrl": manager.ENDPOINT,
                        "headers": {"Authorization": "Bearer VERY_PRIVATE_VALUE"}}),
            ("command", {"command": "npx", "args": ["--api-key", "VERY_PRIVATE_VALUE"]}),
            ("oauth", {"serverUrl": manager.ENDPOINT, "oauth": {"clientSecret": "PRIVATE"}}),
            ("query-key", {"serverUrl": manager.ENDPOINT + "?token=VERY_PRIVATE_VALUE"}),
            ("url-userinfo", {"serverUrl": "https://user:VERY_PRIVATE_VALUE@mcp.context7.com/mcp"}),
            ("disabled", {"serverUrl": manager.ENDPOINT, "disabled": True}),
            ("extra-timeout", {"serverUrl": manager.ENDPOINT, "timeoutSeconds": 60}),
            ("invalid-url", {"serverUrl": "https://[invalid"}),
        ]:
            with self.subTest(name=name):
                self.file.write_text(json.dumps({"mcpServers": {"context7": entry}}))
                original = self.file.read_bytes()
                plan_code, out, _ = self.call("plan")
                self.assertEqual(plan_code, 3)
                self.assertIn("BLOCKED", out)
                self.assertNotIn("PRIVATE", out)
                code, out, _ = self.call("reinstall", "--yes")
                self.assertEqual(code, 3)
                self.assertIn("BLOCKED", out)
                self.assertNotIn("PRIVATE", out)
                self.assertEqual(original, self.file.read_bytes())
                self.assertFalse(self.backup.exists())
                code, out, _ = self.call("status", "--menu")
                self.assertEqual(code, 0)  # User-managed auth is not corruption.
                self.assertNotIn("PRIVATE", out)

    def test_ambiguous_json_is_fail_closed(self):
        bad = [
            b"{",
            b"[]",
            b'{"mcpServers":[]}',
            b'{"mcpServers":{"context7":{},"context7":{"serverUrl":"https://wrong"}}}',
            b'{"mcpServers":{"other":{"command":"safe","command":"not-safe"}}}',
            b"\xff",
        ]
        for raw in bad:
            with self.subTest(raw=raw[:18]):
                self.file.write_bytes(raw)
                self.assertEqual(self.call("plan")[0], 3)
                self.assertEqual(self.call("status", "--menu")[0], 3)
                self.assertEqual(self.call("reinstall", "--yes")[0], 3)
                self.assertEqual(self.file.read_bytes(), raw)
                self.assertFalse(self.backup.exists())

    def test_missing_global_directory_is_optional_and_read_only(self):
        self.configdir.rmdir()
        code, out, _ = self.call("status", "--menu")
        self.assertEqual(code, 0)
        self.assertIn("not installed", out)
        code, out, _ = self.call("plan")
        self.assertEqual(code, 3)
        self.assertIn("BLOCKED", out)
        self.assertEqual(self.call("reinstall", "--yes")[0], 3)
        self.assertFalse(self.configdir.exists())

    def test_fifo_and_symlink_config_rejected(self):
        self.file.symlink_to(self.root / "other")
        self.assertEqual(self.call("status", "--menu")[0], 3)
        self.assertEqual(self.call("reinstall", "--yes")[0], 3)
        self.file.unlink()
        os.mkfifo(self.file, mode=0o600)
        self.assertEqual(self.call("plan")[0], 3)
        self.assertEqual(self.call("reinstall", "--yes")[0], 3)
        self.assertFalse(self.backup.exists())

    def test_cross_role_denial(self):
        os.environ["REMOTE_DEV_ROLE"] = "codex"
        code, _, _ = self.call("reinstall", "--yes")
        self.assertEqual(code, 2)
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
