#!/usr/bin/env python3
"""Role-isolation regressions for the menu's active Context7 MCP test.

All network and vendor CLI calls are mocked. OAuth state is never opened.
"""
from __future__ import annotations

import argparse
import builtins
import contextlib
import importlib.util
from importlib.machinery import SourceFileLoader
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
import tempfile
import time
import types
import unittest
from urllib.request import ProxyHandler
from unittest.mock import patch


def load_module(name, source):
    # The installed AGY command has no .py suffix; give Python its loader.
    loader = SourceFileLoader(name, str(source))
    spec = importlib.util.spec_from_file_location(name, source, loader=loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def select_agy_source(checkout: Path, installed: Path, *, image_smoke: bool) -> Path:
    """Prefer checkout in development; require the installed file in image smoke."""
    if image_smoke:
        if not installed.is_file():
            raise AssertionError("installed Antigravity Context7 entrypoint unavailable")
        return installed
    if checkout.is_file():
        return checkout
    if installed.is_file():
        return installed
    raise AssertionError("Antigravity Context7 entrypoint unavailable")


HERE = Path(__file__).parent
CODEX = HERE / "remote-dev-context7.py"
if not CODEX.is_file():
    CODEX = Path("/usr/local/lib/remote-dev/remote-dev-context7.py")
AGY = select_agy_source(
    HERE / "remote-dev-context7-antigravity.py",
    Path("/usr/local/bin/remote-dev-context7-antigravity"),
    image_smoke=os.environ.get("REMOTE_DEV_MCP_WIRING_IMAGE_SMOKE") == "1",
)
codex = load_module("codex_context7_wiring_fixture", CODEX)
agy = load_module("agy_context7_wiring_fixture", AGY)
SECRET = "ctx7sk-SYNTHETIC_KEY_NEVER_SEND"


class SyntheticProbeError(Exception):
    pass


class SyntheticUnverifiedDocumentation(SyntheticProbeError):
    pass


class FakeProbe:
    ProbeError = SyntheticProbeError
    UnverifiedDocumentation = SyntheticUnverifiedDocumentation
    TOTAL_TEST_SECONDS = 90

    def __init__(self, *, failed=False, unverified=False):
        self.calls = []
        self.deadlines = []
        self.failed = failed
        self.unverified = unverified

    @staticmethod
    def _hard_read_deadline(_remaining):
        return contextlib.nullcontext()

    def probe(self, api_key=None, *, deadline=None):
        self.calls.append(api_key)
        self.deadlines.append(deadline)
        if self.failed:
            raise self.ProbeError("synthetic MCP failure")
        if self.unverified:
            raise self.UnverifiedDocumentation(
                "Context7 query-docs documentation UNVERIFIED (no positive evidence)"
            )
        return (
            "Context7 MCP protocol initialize: PASS",
            "Context7 MCP tools/list: PASS (resolve-library-id, query-docs)",
            "Context7 MCP real tools/call: PASS (2 public documentation calls)",
        )


class FakeHTTPResponse:
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return agy.PING

    def read(self, count=-1):
        return b'{"status":"ok","message":"pong"}'


class FakeOpener:
    def open(self, request, timeout=10):
        assert request.full_url == agy.PING
        return FakeHTTPResponse()


class WiringTests(unittest.TestCase):
    def test_extensionless_installed_agy_source_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp) / "remote-dev-context7-antigravity.py"
            entrypoint = Path(temp) / "remote-dev-context7-antigravity"
            checkout.write_text("IS_INSTALLED_ENTRYPOINT = False\n", encoding="utf-8")
            entrypoint.write_text("IS_INSTALLED_ENTRYPOINT = True\n", encoding="utf-8")
            self.assertEqual(
                select_agy_source(checkout, entrypoint, image_smoke=False), checkout)
            self.assertEqual(
                select_agy_source(checkout, entrypoint, image_smoke=True), entrypoint)
            loaded = load_module("synthetic_extensionless_agy", entrypoint)
            self.assertIs(loaded.IS_INSTALLED_ENTRYPOINT, True)
            entrypoint.unlink()
            with self.assertRaisesRegex(AssertionError, "installed Antigravity"):
                select_agy_source(checkout, entrypoint, image_smoke=True)
            self.assertEqual(
                select_agy_source(checkout, entrypoint, image_smoke=False), checkout)

    def test_installed_probe_executes_real_mcp_logic_with_mocked_network(self):
        """Run the actual installed probe with network mocked, not FakeProbe."""
        fixture = load_module(
            "synthetic_mcp_network_responses",
            HERE / "test_remote_dev_context7_mcp_probe.py",
        )
        installed = Path("/usr/local/lib/remote-dev/remote_dev_context7_mcp_probe.py")
        for label, loader, key in (
            ("codex", codex.load_mcp_probe, SECRET),
            ("antigravity", agy.load_mcp_probe, None),
        ):
            with self.subTest(provider=label):
                actual = loader()
                if installed.exists():
                    self.assertEqual(Path(actual.__file__), installed)
                network = fixture.FakeOpener()
                # Fake only the transport; the protocol implementation,
                # validation, and both real tools/call are executed.
                self.assertEqual(
                    len(actual.probe(api_key=key, opener=network)), 3,
                )
                self.assertEqual(
                    [request["method"] for request, _ in network.calls],
                    ["initialize", "notifications/initialized", "tools/list",
                     "tools/call", "tools/call"],
                )
                for body, headers in network.calls:
                    self.assertEqual(headers.get("context7_api_key"), key)
                    self.assertNotIn(SECRET, json.dumps(body))
                    other = {k: v for k, v in headers.items()
                             if k != "context7_api_key"}
                    self.assertNotIn(SECRET, repr(other))

    def test_slow_ping_is_cut_off_before_real_mcp_calls(self):
        """Both providers' /ping must honor the same wall-clock budget."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex"
            codex_home.mkdir(mode=0o700)
            (codex_home / "config.toml").write_text(
                codex.MANAGED_BLOCK, encoding="utf-8")
            (codex_home / "config.toml").chmod(0o600)
            codex_probe = codex.load_mcp_probe()
            called = []

            def slow_ping():
                time.sleep(0.2)
                called.append("ping-completed")

            with (patch.dict(os.environ, {"CODEX_HOME": str(codex_home),
                                        "REMOTE_DEV_ROLE": "codex"}),
                  patch.object(codex, "bundled_codex_accepts_config"),
                  patch.object(codex, "load_mcp_probe", return_value=codex_probe),
                  patch.object(codex, "hosted_ping", side_effect=slow_ping),
                  patch.object(codex_probe, "TOTAL_TEST_SECONDS", 0.04),
                  contextlib.redirect_stdout(io.StringIO())):
                with self.assertRaises(codex.Context7Error):
                    codex.command_test(codex.Paths(), argparse.Namespace(yes=True))
            self.assertEqual(called, [])

            agy_home = root / "antigravity"
            agy_home.mkdir(mode=0o700)
            (agy_home / "mcp_config.json").write_text(
                json.dumps({"mcpServers": {"context7": agy.ENTRY}}),
                encoding="utf-8",
            )
            (agy_home / "mcp_config.json").chmod(0o600)
            agy_probe = agy.load_mcp_probe()

            class SlowPingOpener:
                def open(self, request, timeout=10):
                    del request, timeout
                    time.sleep(0.2)
                    called.append("agy-ping-completed")
                    return FakeHTTPResponse()

            with (patch.dict(os.environ, {"REMOTE_DEV_ROLE": "antigravity"}),
                  patch.object(agy, "load_mcp_probe", return_value=agy_probe),
                  patch.object(agy, "build_opener", return_value=SlowPingOpener()),
                  patch.object(agy_probe, "TOTAL_TEST_SECONDS", 0.04),
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(agy.test(agy_home), 3)
            self.assertEqual(called, [])

    def test_both_pings_ignore_proxies_and_sanitize_broken_http_json(self):
        """The preflight /ping must not consult HTTPS_PROXY or crash on JSON."""
        deep_json = b"[" * 1200 + b"0" + b"]" * 1200
        for label, payload, broken in (
            ("valid", b'{"status":"ok","message":"pong"}', False),
            ("deep-json", deep_json, False),
            ("incomplete", None, True),
        ):
            with self.subTest(ping=label):
                def checked_opener(*handlers):
                    self.assertTrue(
                        any(isinstance(h, ProxyHandler) and h.proxies == {}
                            for h in handlers),
                        "ping must explicitly disable environment proxies",
                    )
                    class Response(FakeHTTPResponse):
                        def __init__(self, url):
                            self.url = url
                        def geturl(self):
                            return self.url
                        def read(self, count=-1):
                            if broken:
                                raise IncompleteRead(b"synthetic", 10)
                            return payload if count < 0 else payload[:count]
                    class Opener:
                        def open(self, request, timeout=10):
                            self_timeout = timeout
                            assert self_timeout == 10
                            return Response(request.full_url)
                    return Opener()

                with (patch.dict(os.environ, {
                          "HTTPS_PROXY": "http://unsafe-proxy.invalid:4321",
                          "https_proxy": "http://unsafe-proxy.invalid:4321",
                      }),
                      patch.object(codex, "build_opener", side_effect=checked_opener)):
                    if label == "valid":
                        self.assertIsNone(codex.hosted_ping())
                    else:
                        with self.assertRaises(codex.Context7Error) as err:
                            codex.hosted_ping()
                        self.assertNotIn("synthetic", str(err.exception))
                        self.assertNotIn("RecursionError", str(err.exception))

                with tempfile.TemporaryDirectory() as tmp:
                    home = Path(tmp)
                    config = home / "mcp_config.json"
                    config.write_text(
                        json.dumps({"mcpServers": {"context7": agy.ENTRY}}),
                        encoding="utf-8",
                    )
                    config.chmod(0o600)
                    fake = FakeProbe()
                    with (patch.dict(os.environ, {
                              "REMOTE_DEV_ROLE": "antigravity",
                              "HTTPS_PROXY": "http://unsafe-proxy.invalid:4321",
                              "https_proxy": "http://unsafe-proxy.invalid:4321",
                          }),
                          patch.object(agy, "build_opener", side_effect=checked_opener),
                          patch.object(agy, "load_mcp_probe", return_value=fake),
                          contextlib.redirect_stdout(io.StringIO()) as output):
                        code = agy.test(home)
                    self.assertEqual(code, 0 if label == "valid" else 3)
                    self.assertNotIn("synthetic", output.getvalue())
                    if label == "valid":
                        self.assertEqual(fake.calls, [None])
                    else:
                        self.assertEqual(fake.calls, [])
                        self.assertIn("hosted endpoint test failed", output.getvalue())

    def test_codex_ping_propagates_exact_probe_timer_error(self):
        # The deadline exception must escape hosted_ping's network handler,
        # then be translated by command_test to a precise, fixed message.
        actual = codex.load_mcp_probe()

        class ExpiredPingOpener:
            def open(self, request, *, timeout):
                del request, timeout
                raise actual.ProbeError("MCP response exceeded its time limit")

        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex"
            home.mkdir(mode=0o700)
            config = home / "config.toml"
            config.write_text(codex.MANAGED_BLOCK, encoding="utf-8")
            config.chmod(0o600)
            with (
                patch.dict(os.environ, {"CODEX_HOME": str(home),
                                        "REMOTE_DEV_ROLE": "codex"}),
                patch.object(codex, "build_opener", return_value=ExpiredPingOpener()),
                patch.object(codex, "bundled_codex_accepts_config"),
                patch.object(codex, "load_mcp_probe", return_value=actual),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaisesRegex(
                    codex.Context7Error,
                    "hosted HTTP ping FAILED: MCP response exceeded its time limit",
                ):
                    codex.command_test(codex.Paths(), argparse.Namespace(yes=True))

    def test_unverified_does_not_report_tool_failed_in_both_managers(self):
        """Ambiguous docs require nonzero outcome but not a FAILED label."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex_home = root / "codex"
            codex_home.mkdir(mode=0o700)
            config = codex_home / "config.toml"
            config.write_text(codex.MANAGED_BLOCK, encoding="utf-8")
            config.chmod(0o600)
            with (patch.dict(os.environ, {"CODEX_HOME": str(codex_home),
                                          "REMOTE_DEV_ROLE": "codex"}),
                  patch.object(codex, "bundled_codex_accepts_config"),
                  patch.object(codex, "hosted_ping"),
                  patch.object(codex, "load_mcp_probe",
                               return_value=FakeProbe(unverified=True)),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                with self.assertRaises(codex.Context7Error) as exc:
                    codex.command_test(codex.Paths(), argparse.Namespace(yes=True))
            self.assertIn("MCP tool verification UNVERIFIED", str(exc.exception))
            self.assertNotIn("MCP tool verification FAILED", str(exc.exception))
            self.assertNotIn(SECRET, str(exc.exception) + output.getvalue())

            home = root / "antigravity"
            home.mkdir(mode=0o700)
            config = home / "mcp_config.json"
            config.write_text(
                json.dumps({"mcpServers": {"context7": agy.ENTRY}}),
                encoding="utf-8",
            )
            config.chmod(0o600)
            with (patch.dict(os.environ, {"REMOTE_DEV_ROLE": "antigravity"}),
                  patch.object(agy, "build_opener", return_value=FakeOpener()),
                  patch.object(agy, "load_mcp_probe",
                               return_value=FakeProbe(unverified=True)),
                  contextlib.redirect_stdout(io.StringIO()) as output):
                self.assertEqual(agy.test(home), 3)
            self.assertIn("MCP tool verification UNVERIFIED", output.getvalue())
            self.assertNotIn("MCP tool verification FAILED", output.getvalue())
            self.assertNotIn(SECRET, output.getvalue())

    def test_codex_key_forwarded_only_to_codex_mcp_probe(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp) / "codex"
            home.mkdir(mode=0o700)
            config = home / "config.toml"
            config.write_text(codex.MANAGED_BLOCK, encoding="utf-8")
            config.chmod(0o600)
            key_dir = home / ".remote-dev-context7"
            key_dir.mkdir(mode=0o700)
            key_file = key_dir / "api-key"
            key_file.write_text(SECRET, encoding="utf-8")
            key_file.chmod(0o600)
            with patch.dict(os.environ, {"CODEX_HOME": str(home), "REMOTE_DEV_ROLE": "codex"}):
                paths = codex.Paths()
                before = (config.read_bytes(), key_file.read_bytes())
                for failure in (False, True):
                    with self.subTest(failure=failure):
                        fake = FakeProbe(failed=failure)
                        with (patch.object(codex, "bundled_codex_accepts_config"),
                              patch.object(codex, "hosted_ping"),
                              patch.object(codex, "load_mcp_probe", return_value=fake),
                              contextlib.redirect_stdout(io.StringIO()) as stdout):
                            if failure:
                                with self.assertRaises(codex.Context7Error):
                                    codex.command_test(paths, argparse.Namespace(yes=True))
                            else:
                                self.assertEqual(
                                    codex.command_test(paths, argparse.Namespace(yes=True)), 0)
                        self.assertEqual(fake.calls, [SECRET])
                        self.assertEqual(len(fake.deadlines), 1)
                        self.assertIsInstance(fake.deadlines[0], float)
                        self.assertNotIn(SECRET, stdout.getvalue())
                        if not failure:
                            self.assertIn("Codex agent-native MCP tool execution: NOT VERIFIED",
                                          stdout.getvalue())
                            self.assertIn("MCP real tools/call: PASS", stdout.getvalue())
                self.assertEqual((config.read_bytes(), key_file.read_bytes()), before)

    def test_antigravity_uses_anonymous_probe_not_oauth_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "gemini"
            root.mkdir(mode=0o700)
            config = root / "mcp_config.json"
            config.write_text(json.dumps({"mcpServers": {"context7": agy.ENTRY}}))
            config.chmod(0o600)
            oauth = root / "mcp_oauth_tokens.json"
            oauth.write_text(SECRET, encoding="utf-8")
            oauth.chmod(0o600)
            before = (config.read_bytes(), oauth.read_bytes())
            # A byte-for-byte check alone cannot detect unauthorized reads.
            # Intercept all standard Python open paths during AGY testing.
            original_builtin_open = builtins.open
            original_io_open = io.open
            original_os_open = os.open

            def guard_oauth(file, *, operation):
                if isinstance(file, (str, bytes, os.PathLike)):
                    candidate = Path(os.fsdecode(file))
                    if candidate == oauth or candidate.name == oauth.name:
                        raise AssertionError(
                            f"Antigravity inspected its private OAuth store via {operation}"
                        )

            def guarded_builtin(file, *args, **kwargs):
                guard_oauth(file, operation="builtins.open")
                return original_builtin_open(file, *args, **kwargs)

            def guarded_io(file, *args, **kwargs):
                guard_oauth(file, operation="io.open/Path.open")
                return original_io_open(file, *args, **kwargs)

            def guarded_os(file, *args, **kwargs):
                guard_oauth(file, operation="os.open")
                return original_os_open(file, *args, **kwargs)

            with patch.dict(os.environ, {"REMOTE_DEV_ROLE": "antigravity"}):
                for failure in (False, True):
                    with self.subTest(failure=failure):
                        fake = FakeProbe(failed=failure)
                        with (patch.object(agy, "build_opener", return_value=FakeOpener()),
                              patch.object(agy, "load_mcp_probe", return_value=fake),
                              patch.object(builtins, "open", guarded_builtin),
                              patch.object(io, "open", guarded_io),
                              patch.object(os, "open", guarded_os),
                              contextlib.redirect_stdout(io.StringIO()) as stdout):
                            # Prove the guard itself detects a read before
                            # accepting AGY's zero-access contract.
                            with self.assertRaisesRegex(
                                AssertionError, "inspected its private OAuth store"
                            ):
                                oauth.read_bytes()
                            code = agy.test(root)
                        self.assertEqual(code, 3 if failure else 0)
                        self.assertEqual(fake.calls, [None])
                        self.assertEqual(len(fake.deadlines), 1)
                        self.assertIsInstance(fake.deadlines[0], float)
                        self.assertNotIn(SECRET, stdout.getvalue())
                        if not failure:
                            self.assertIn("Antigravity OAuth and agent-native MCP tool execution: NOT VERIFIED",
                                          stdout.getvalue())
                            self.assertIn("Context7 request mode: anonymous", stdout.getvalue())
                # Loader faults happen before probe is bound. They must
                # not throw UnboundLocalError or expose the OAuth fixture.
                with (patch.object(agy, "build_opener", return_value=FakeOpener()),
                      patch.object(agy, "load_mcp_probe",
                                   side_effect=SyntaxError("synthetic invalid helper")),
                      patch.object(builtins, "open", guarded_builtin),
                      patch.object(io, "open", guarded_io),
                      patch.object(os, "open", guarded_os),
                      contextlib.redirect_stdout(io.StringIO()) as stdout):
                    self.assertEqual(agy.test(root), 3)
                self.assertIn("probe unavailable", stdout.getvalue())
                self.assertNotIn(SECRET, stdout.getvalue())
            self.assertEqual((config.read_bytes(), oauth.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
