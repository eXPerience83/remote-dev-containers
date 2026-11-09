#!/usr/bin/env python3
"""Offline contract tests for conservative browser MCP provisioning."""
import importlib.util
from pathlib import Path
import json
import tempfile
import unittest

SOURCE = Path(__file__).with_name("remote-dev-browser-config.py")
spec = importlib.util.spec_from_file_location("browser_config", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrowserConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private"
        self.path.mkdir(mode=0o700)

    def test_codex_preserves_existing_mcp_and_is_idempotent(self):
        config = self.path / "config.toml"
        config.write_text('[mcp_servers.context7]\nurl = "https://example.test/mcp"\n')
        self.assertEqual(module.reconcile("codex", self.path), "configured")
        data = config.read_text()
        self.assertIn("mcp_servers.context7", data)
        self.assertIn("mcp_servers.playwright", data)
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), data)

    def test_codex_user_server_is_not_replaced(self):
        config = self.path / "config.toml"
        content = '[mcp_servers.playwright]\ncommand = "custom"\nenabled = false\n'
        config.write_text(content)
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), content)

    def test_antigravity_preserves_existing_mcp_and_is_idempotent(self):
        config = self.path / "mcp_config.json"
        config.write_text('{"mcpServers":{"other":{"command":"foo"}},"setting":42}')
        self.assertEqual(module.reconcile("antigravity", self.path), "configured")
        obj = json.loads(config.read_text())
        self.assertEqual(obj["setting"], 42)
        self.assertEqual(obj["mcpServers"]["other"]["command"], "foo")
        self.assertEqual(obj["mcpServers"]["playwright"]["command"], module.BROWSER_COMMAND)
        self.assertEqual(module.reconcile("antigravity", self.path), "existing")

    def test_invalid_config_is_never_overwritten(self):
        config = self.path / "config.toml"
        config.write_text("[invalid\n")
        with self.assertRaises(module.tomllib.TOMLDecodeError):
            module.reconcile("codex", self.path)
        self.assertEqual(config.read_text(), "[invalid\n")

    def test_symlink_config_rejected(self):
        target = self.path / "other"
        target.write_text("untouched")
        (self.path / "config.toml").symlink_to(target)
        with self.assertRaises(OSError):
            module.reconcile("codex", self.path)
        self.assertEqual(target.read_text(), "untouched")

    def test_new_provider_configuration(self):
        self.assertEqual(module.reconcile("codex", self.path), "configured")
        self.assertIn(module.BROWSER_COMMAND, (self.path / "config.toml").read_text())
        self.assertEqual(module.reconcile("antigravity", self.path), "configured")
        self.assertIn("playwright", (self.path / "mcp_config.json").read_text())


if __name__ == "__main__":
    unittest.main()
