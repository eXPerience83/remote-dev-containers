#!/usr/bin/env python3
"""Offline contract tests for conservative browser MCP provisioning."""
import importlib.util
from pathlib import Path
import json
import tempfile
import tomllib
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
        parsed = tomllib.loads(data)
        self.assertEqual(parsed["mcp_servers"]["playwright"]["env"],
                         {"REMOTE_DEV_ROLE": "codex"})
        self.assertEqual(parsed["mcp_servers"]["context7"]["url"],
                         "https://example.test/mcp")
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), data)

    def test_codex_user_server_is_not_replaced(self):
        config = self.path / "config.toml"
        content = '[mcp_servers.playwright]\ncommand = "custom"\nenabled = false\n'
        config.write_text(content)
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), content)

    def test_codex_repairs_only_exact_legacy_generated_entry(self):
        config = self.path / "config.toml"
        original = '[mcp_servers.context7]\nurl = "https://example.test/mcp"\n'
        original += module.CODEX_ENTRY_LEGACY
        config.write_text(original)
        self.assertEqual(module.reconcile("codex", self.path), "configured")
        updated = config.read_text()
        self.assertEqual(updated, original.replace(
            module.CODEX_ENTRY_LEGACY, module.CODEX_ENTRY))
        self.assertEqual(tomllib.loads(updated)["mcp_servers"]["playwright"]["env"],
                         {"REMOTE_DEV_ROLE": "codex"})
        self.assertEqual(module.reconcile("codex", self.path), "existing")

    def test_codex_reformatted_legacy_entry_requires_manual_review(self):
        config = self.path / "config.toml"
        original = module.CODEX_ENTRY_LEGACY.replace(
            "enabled = true", "enabled=true")
        config.write_text(original)
        self.assertEqual(tomllib.loads(original)["mcp_servers"]["playwright"],
                         module.LEGACY_CODEX_FIELDS)
        with self.assertRaisesRegex(
                module.UnsafeConfig, "manual review required"):
            module.reconcile("codex", self.path)
        self.assertEqual(config.read_text(), original)

    def test_codex_user_modified_legacy_entry_is_never_replaced(self):
        config = self.path / "config.toml"
        original = module.CODEX_ENTRY_LEGACY.replace(
            "tool_timeout_sec = 90", "tool_timeout_sec = 180")
        config.write_text(original)
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), original)

    def test_codex_inline_table_is_not_corrupted(self):
        config = self.path / "config.toml"
        original = ('mcp_servers = { context7 = { url = '
                    '"https://example.test/mcp" } }\n')
        self.assertEqual(tomllib.loads(original)["mcp_servers"]["context7"]["url"],
                         "https://example.test/mcp")
        config.write_text(original)
        with self.assertRaises(module.UnsafeConfig):
            module.reconcile("codex", self.path)
        self.assertEqual(config.read_text(), original)

    def test_codex_inline_user_playwright_is_preserved(self):
        config = self.path / "config.toml"
        original = ('mcp_servers = { playwright = { command = '
                    '"user-owned", enabled = false } }\n')
        config.write_text(original)
        self.assertEqual(module.reconcile("codex", self.path), "existing")
        self.assertEqual(config.read_text(), original)

    def test_antigravity_preserves_existing_mcp_and_is_idempotent(self):
        config = self.path / "mcp_config.json"
        config.write_text('{"mcpServers":{"other":{"command":"foo"}},"setting":42}')
        self.assertEqual(module.reconcile("antigravity", self.path), "configured")
        obj = json.loads(config.read_text())
        self.assertEqual(obj["setting"], 42)
        self.assertEqual(obj["mcpServers"]["other"]["command"], "foo")
        self.assertEqual(obj["mcpServers"]["playwright"]["command"], module.BROWSER_COMMAND)
        self.assertEqual(module.reconcile("antigravity", self.path), "existing")

    def test_immutable_mcp_policy_disables_page_tool_registration(self):
        policy = json.loads(
            (SOURCE.parent.parent / "config" / "playwright-mcp.json").read_text()
        )
        self.assertEqual(policy["browser"]["browserName"], "chromium")
        self.assertTrue(policy["browser"]["isolated"])
        self.assertIs(policy["webmcp"], False)
        self.assertIs(policy["saveSession"], False)

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
