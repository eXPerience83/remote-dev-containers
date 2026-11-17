#!/usr/bin/env python3
"""Offline regression tests for the real Context7 MCP probe. Never access network."""
import importlib.util
import io
import json
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

SOURCE = Path(__file__).with_name("remote_dev_context7_mcp_probe.py")
if not SOURCE.is_file():
    SOURCE = Path("/usr/local/lib/remote-dev/remote_dev_context7_mcp_probe.py")
spec = importlib.util.spec_from_file_location("context7_probe_test_subject", SOURCE)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
SECRET = "ctx7sk-TEST_ONLY_DO_NOT_USE"


class FakeResponse:
    def __init__(self, value, *, status=200, content_type="application/json",
                 session="syntheticMcpSession", url=probe.ENDPOINT):
        self.status = status
        self.headers = {"Content-Type": content_type, "Mcp-Session-Id": session}
        self.value = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.url = url
        self.position = 0

    def readline(self, limit=-1):
        if self.position >= len(self.value):
            return b""
        end = self.value.find(b"\n", self.position)
        end = len(self.value) if end < 0 else end + 1
        if limit >= 0:
            end = min(end, self.position + limit)
        result = self.value[self.position:end]
        self.position = end
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit=-1):
        return self.value[:limit] if limit >= 0 else self.value


class FakeOpener:
    def __init__(self, fault=None):
        self.calls = []
        self.fault = fault

    def open(self, request, *, timeout):
        assert timeout == probe.TIMEOUT_SECONDS
        assert request.full_url == probe.ENDPOINT
        assert request.get_method() == "POST"
        headers = {k.casefold(): v for k, v in request.header_items()}
        body = json.loads(request.data)
        self.calls.append((body, headers))
        method = body["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {}}
        elif method == "notifications/initialized":
            return FakeResponse(b"", status=202)
        elif method == "tools/list":
            result = {"tools": [
                {"name": "resolve-library-id"}, {"name": "query-docs"}]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "Public docs returned"}],
                      "isError": False}
        else:
            raise AssertionError("unexpected MCP method " + method)
        if self.fault and self.fault[0] == method:
            kind = self.fault[1]
            if kind == "redirect":
                return FakeResponse({"jsonrpc": "2.0", "id": body["id"],
                                     "result": result}, url="https://untrusted.invalid/mcp")
            if kind == "oversize":
                return FakeResponse(b"x" * (probe.MAX_RESPONSE_BYTES + 1))
            if kind == "no-tools":
                return FakeResponse({"jsonrpc": "2.0", "id": body["id"],
                                     "result": {"tools": []}})
            if kind == "tool-error":
                return FakeResponse({"jsonrpc": "2.0", "id": body["id"],
                                     "result": {"isError": True, "content": [
                                         {"type": "text", "text": SECRET}]}})
            if kind == "http-error":
                return FakeResponse(b"", status=401)
            if kind == "bad-json":
                return FakeResponse(b"{")
            if kind == "bad-sse":
                return FakeResponse(b"data: not-json\n\n",
                                    content_type="text/event-stream")
            if kind == "duplicate":
                value = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                    "result": result})
                return FakeResponse(("data: " + value + "\n\ndata: " +
                                     value + "\n\n").encode(),
                                    content_type="text/event-stream")
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if method == "tools/list":
            return FakeResponse(("event: message\ndata: " + json.dumps(message) +
                                 "\n\n").encode(), content_type="text/event-stream")
        return FakeResponse(message)


class ProbeTests(TestCase):
    def test_both_credential_modes_make_real_mcp_calls(self):
        for key in (None, SECRET):
            with self.subTest(key_supplied=key is not None):
                opener = FakeOpener()
                lines = probe.probe(api_key=key, opener=opener)
                self.assertEqual(len(lines), 3)
                self.assertTrue(all("PASS" in line for line in lines))
                self.assertEqual([b["method"] for b, _ in opener.calls], [
                    "initialize", "notifications/initialized", "tools/list",
                    "tools/call", "tools/call"])
                self.assertEqual(
                    [b["params"]["name"] for b, _ in opener.calls[-2:]],
                    ["resolve-library-id", "query-docs"])
                self.assertEqual(
                    opener.calls[-1][0]["params"]["arguments"]["libraryId"],
                    "/psf/requests")
                self.assertTrue(all(headers.get("mcp-session-id") ==
                                    "syntheticMcpSession" for _, headers
                                    in opener.calls[1:]))
                for _, headers in opener.calls:
                    self.assertEqual(headers.get("context7_api_key"), key)
                    self.assertNotIn(SECRET, str(headers) if key is None else "")
                self.assertNotIn(SECRET, repr(lines))

    def test_fail_closed_on_transport_and_tool_failures(self):
        for fault in (
            ("initialize", "redirect"),
            ("initialize", "bad-json"),
            ("initialize", "oversize"),
            ("tools/list", "no-tools"),
            ("tools/list", "bad-sse"),
            ("tools/call", "tool-error"),
            ("tools/call", "http-error"),
        ):
            with self.subTest(fault=fault):
                opener = FakeOpener(fault)
                with self.assertRaises(probe.ProbeError) as exc:
                    probe.probe(api_key=SECRET, opener=opener)
                self.assertNotIn(SECRET, str(exc.exception))

    def test_injected_secret_rejected_before_network(self):
        for candidate in ("abc\nAuthorization: Bearer secret", "", "unsafe space"):
            opener = FakeOpener()
            with self.assertRaises(probe.ProbeError):
                probe.probe(api_key=candidate, opener=opener)
            self.assertEqual(opener.calls, [])

    def test_real_opener_disables_environment_proxies_and_redirects(self):
        args_seen = []
        def fake_build(*handlers):
            args_seen.extend(handlers)
            return object()
        with patch.object(probe, "build_opener", side_effect=fake_build):
            self.assertIsNotNone(probe._open_client())
        self.assertTrue(any(isinstance(h, probe.ProxyHandler) and
                            h.proxies == {} for h in args_seen))
        self.assertTrue(any(isinstance(h, probe.NoRedirect) for h in args_seen))
        self.assertTrue(any(isinstance(h, probe.HTTPSHandler) for h in args_seen))


if __name__ == "__main__":
    main()
