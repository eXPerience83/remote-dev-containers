#!/usr/bin/env python3
"""Offline regression tests for the real Context7 MCP probe. Never access network."""
import importlib.util
import io
from http.client import IncompleteRead
import json
import time
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

    def read1(self, limit):
        if self.position >= len(self.value):
            return b""
        end = min(len(self.value), self.position + limit)
        result = self.value[self.position:end]
        self.position = end
        return result


class FakeOpener:
    def __init__(self, fault=None, *, negotiated_protocol="2025-03-26"):
        self.calls = []
        self.fault = fault
        self.negotiated_protocol = negotiated_protocol
        self.session = "opaque.v1" if fault == ("initialize", "opaque-session") else "syntheticMcpSession"

    def open(self, request, *, timeout):
        assert timeout == probe.TIMEOUT_SECONDS
        assert request.full_url == probe.ENDPOINT
        assert request.get_method() == "POST"
        headers = {k.casefold(): v for k, v in request.header_items()}
        body = json.loads(request.data)
        self.calls.append((body, headers))
        method = body["method"]
        if method == "initialize":
            result = {
                "protocolVersion": self.negotiated_protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "Context7", "version": "4.0.0"},
            }
        elif method == "notifications/initialized":
            if self.fault == ("notifications/initialized", "bad-notification-status"):
                return FakeResponse(b"", status=200, session=self.session)
            if self.fault == ("notifications/initialized", "bad-notification-body"):
                return FakeResponse(b'{"error":"ignored"}', status=202, session=self.session)
            return FakeResponse(b"", status=202, session=self.session)
        elif method == "tools/list":
            if self.fault == ("tools/list", "paged"):
                cursor = body.get("params", {}).get("cursor")
                if cursor is None:
                    result = {"tools": [{"name": "resolve-library-id",
                                          "inputSchema": {"type": "object"}}],
                              "nextCursor": "opaque.cursor"}
                elif cursor == "opaque.cursor":
                    result = {"tools": [{"name": "query-docs",
                                          "inputSchema": {"type": "object"}}]}
                else:
                    raise AssertionError("MCP tools/list received wrong pagination cursor")
            elif self.fault == ("tools/list", "loop-cursor"):
                result = {"tools": [], "nextCursor": "loop"}
            else:
                result = {"tools": [
                    {"name": "resolve-library-id", "inputSchema": {"type": "object"}},
                    {"name": "query-docs", "inputSchema": {"type": "object"}}]}
        elif method == "tools/call":
            if body["params"]["name"] == "resolve-library-id":
                content = (
                    "Available Libraries:\n\n- Name: Requests\n"
                    "- Context7-compatible library ID: /psf/requests\n"
                    "- Source Reputation: High"
                )
            else:
                content = (
                    "### Timeout configuration for Python Requests\n"
                    "Source: https://requests.readthedocs.io/en/latest/user/advanced/\n"
                    "Use requests.get(url, timeout=5) to set the HTTP timeout."
                )
            result = {"content": [{"type": "text", "text": content}],
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
            if kind == "no-public-docs":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": {"content": [{"type": "text",
                                           "text": "No documentation found for Requests timeout"}]}
                })
            if kind == "wrong-library":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": {"content": [{"type": "text",
                                           "text": "Available Libraries:\n- Library ID: /other/project"}]}
                })
            if kind == "irrelevant-docs":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": {"content": [{"type": "text",
                                           "text": "Unrelated information about cooking"}]}
                })
            if kind == "bad-initialize-capabilities":
                bad = dict(result)
                bad["capabilities"] = {}
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"], "result": bad})
            if kind == "bad-initialize-server-info":
                bad = dict(result)
                bad["serverInfo"] = {}
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"], "result": bad})
            if kind == "bad-tool-descriptors":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": {"tools": [{"name": "resolve-library-id"},
                                         {"name": "query-docs"}]}})
            if kind == "bool-id":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": True, "result": result})
            if kind == "bad-notification-status":
                return FakeResponse(b"", status=200, session=self.session)
            if kind == "bad-notification-body":
                return FakeResponse(b'{"error":"ignored"}', status=202, session=self.session)
            if kind == "reflected-session":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"], "result": result},
                    session=SECRET)
            if kind == "reflected-cursor":
                return FakeResponse({
                    "jsonrpc": "2.0", "id": body["id"],
                    "result": {"tools": [], "nextCursor": SECRET}})
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
            if kind == "primed-sse":
                value = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                    "result": result}).encode()
                return FakeResponse(
                    b"id: ready\ndata:\n\n" + b"data: " + value + b"\n\n",
                    content_type="text/event-stream", session=self.session,
                )
            if kind == "terminal-cr":
                value = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                    "result": result}).encode()
                class OpenSSE(FakeResponse):
                    def read1(self, limit):
                        if self.position >= len(self.value):
                            raise AssertionError("valid final CR was not dispatched immediately")
                        return super().read1(limit)
                return OpenSSE(b"data: " + value + b"\r\r",
                               content_type="text/event-stream", session=self.session)
            if kind == "opaque-session":
                return FakeResponse(
                    {"jsonrpc": "2.0", "id": body["id"], "result": result},
                    session="opaque.v1",
                )
            if kind == "future-protocol":
                future = dict(result)
                future["protocolVersion"] = "2099-01-01"
                return FakeResponse(
                    {"jsonrpc": "2.0", "id": body["id"], "result": future})
            if kind == "incomplete-transfer":
                class Interrupted(FakeResponse):
                    def read1(self, limit):
                        del limit
                        raise IncompleteRead(b"some-secret-body", 1024)
                return Interrupted(
                    {"jsonrpc": "2.0", "id": body["id"], "result": result},
                    content_type="text/event-stream",
                )
            if kind == "duplicate":
                value = json.dumps({"jsonrpc": "2.0", "id": body["id"],
                                    "result": result})
                return FakeResponse(("data: " + value + "\n\ndata: " +
                                     value + "\n\n").encode(),
                                    content_type="text/event-stream")
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        if method == "tools/list":
            return FakeResponse(("event: message\ndata: " + json.dumps(message) +
                                 "\n\n").encode(), content_type="text/event-stream",
                            session=self.session)
        return FakeResponse(message, session=self.session)


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
                for body, headers in opener.calls:
                    self.assertEqual(headers.get("context7_api_key"), key)
                    other_headers = {
                        name: value for name, value in headers.items()
                        if name != "context7_api_key"
                    }
                    self.assertNotIn(SECRET, repr(other_headers))
                    self.assertNotIn(SECRET, json.dumps(body))
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
            ("tools/list", "incomplete-transfer"),
            ("initialize", "future-protocol"),
            ("tools/list", "loop-cursor"),
            ("initialize", "bad-initialize-capabilities"),
            ("initialize", "bad-initialize-server-info"),
            ("initialize", "bool-id"),
            ("tools/list", "bad-tool-descriptors"),
            ("tools/call", "no-public-docs"),
            ("tools/call", "wrong-library"),
            ("tools/call", "irrelevant-docs"),
            ("notifications/initialized", "bad-notification-status"),
            ("notifications/initialized", "bad-notification-body"),
            ("initialize", "reflected-session"),
            ("tools/list", "reflected-cursor"),
        ):
            with self.subTest(fault=fault):
                opener = FakeOpener(fault)
                with self.assertRaises(probe.ProbeError) as exc:
                    probe.probe(api_key=SECRET, opener=opener)
                self.assertNotIn(SECRET, str(exc.exception))

    def test_sse_literal_unicode_separator_and_crlf_framing(self):
        # U+2028 is a Unicode line separator, but not an SSE delimiter.
        result = {"content": [{"type": "text", "text": "public A\u2028B"}]}
        message = {"jsonrpc": "2.0", "id": 2, "result": result}
        stream = (
            b"event: message\r\ndata: " +
            json.dumps(message, ensure_ascii=False).encode("utf-8") +
            b"\r\n\r\n"
        )
        self.assertEqual(
            probe._extract_message(stream, "text/event-stream", 2), result,
        )
        # Only a *strictly* blank line dispatches. A line consisting of a
        # space is an unknown SSE field, not an event boundary.
        text = json.dumps(message, separators=(",", ":"), ensure_ascii=False)
        split_at = text.index(",") + 1
        spaced = (
            "data: " + text[:split_at] + "\n \ndata: " +
            text[split_at:] + "\n\n"
        ).encode("utf-8")
        self.assertEqual(
            probe._extract_message(spaced, "text/event-stream", 2), result,
        )

    def test_real_sse_transport_handles_utf8_u2028_across_byte_reads(self):
        # Exercise the production _exchange SSE loop, not a framing helper.
        # The literal U+2028 occupies three UTF-8 bytes, split across read1.
        opener = FakeOpener()
        normal_open = opener.open

        class FragmentedResponse(FakeResponse):
            def read1(self, limit):
                return super().read1(min(limit, 1))

        def fragmented_sse(request, *, timeout):
            body = json.loads(request.data)
            if body["method"] != "tools/list":
                return normal_open(request, timeout=timeout)
            result = {
                "tools": [
                    {"name": "resolve-library-id", "inputSchema": {"type": "object"},
                     "description": "Example A\u2028Example B"},
                    {"name": "query-docs", "inputSchema": {"type": "object"}},
                ]
            }
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": body["id"], "result": result},
                ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")
            self.assertIn("\u2028".encode("utf-8"), payload)
            return FragmentedResponse(
                b"event: message\r\ndata: " + payload + b"\r\n\r\n",
                content_type="text/event-stream", session=opener.session,
            )

        opener.open = fragmented_sse
        self.assertEqual(len(probe.probe(opener=opener)), 3)
        self.assertEqual(
            [body["method"] for body, _ in opener.calls],
            ["initialize", "notifications/initialized", "tools/call", "tools/call"],
        )

    def test_no_matching_reply_is_distinct_from_duplicate_reply(self):
        message = json.dumps({
            "jsonrpc": "2.0", "id": 99, "result": {"ok": True},
        }).encode()
        with self.assertRaises(probe.NoMatchingReply):
            probe._extract_message(
                b"data: " + message + b"\n\n", "text/event-stream", 2,
            )
        with self.assertRaises(probe.ProbeError) as error:
            probe._extract_message(
                b"data: " + message + b"\n\ndata: " + message + b"\n\n",
                "text/event-stream", 99,
            )
        self.assertNotIsInstance(error.exception, probe.NoMatchingReply)

    def test_valid_requests_docs_can_quote_failure_phrases(self):
        opener = FakeOpener()
        normal_open = opener.open
        def with_error_example(request, *, timeout):
            response = normal_open(request, timeout=timeout)
            body = json.loads(request.data)
            if (body["method"] == "tools/call"
                    and body["params"]["name"] == "query-docs"):
                reply = json.loads(response.value)
                reply["result"]["content"][0]["text"] += (
                    "\n\nError handling example:\n"
                    "# request failed after an unauthorized response\n"
                    "# rate limit example; see requests.get(url, timeout=5)"
                )
                return FakeResponse(reply, session=opener.session)
            return response
        opener.open = with_error_example
        self.assertEqual(len(probe.probe(opener=opener)), 3)

    def test_explicit_failure_status_with_positive_markers_is_not_pass(self):
        content = (
            "Rate limit exceeded; upgrade your plan\n"
            "### Requests timeout\n"
            "https://requests.readthedocs.io/en/latest/user/advanced/\n"
            "requests.get(url, timeout=5)"
        )
        self.assertFalse(probe._has_public_content(
            {"content": [{"type": "text", "text": content}]},
            method="query-docs",
        ))

    def test_sse_priming_and_terminal_cr_without_eof(self):
        for kind in ("primed-sse", "terminal-cr"):
            with self.subTest(kind=kind):
                opener = FakeOpener(fault=("tools/list", kind))
                self.assertEqual(len(probe.probe(opener=opener)), 3)

    def test_single_cumulative_deadline_across_mcp_exchanges(self):
        opener = FakeOpener()
        real_open = opener.open
        def slowed_open(request, *, timeout):
            time.sleep(0.04)
            return real_open(request, timeout=timeout)
        opener.open = slowed_open
        with self.assertRaisesRegex(probe.ProbeError, "time limit"):
            probe.probe(
                opener=opener, deadline=time.monotonic() + 0.09)
        # The 3rd or later operation must not gain a new 25-second budget.
        self.assertLess(len(opener.calls), 5)

    def test_protocol_cursor_and_visible_ascii_session_ids(self):
        opener = FakeOpener(fault=("initialize", "opaque-session"))
        probe.probe(opener=opener)
        self.assertTrue(all(
            headers.get("mcp-session-id") == "opaque.v1"
            for _, headers in opener.calls[1:]
        ))
        for negotiated in sorted(probe.SUPPORTED_PROTOCOL_VERSIONS):
            supported = FakeOpener(negotiated_protocol=negotiated)
            self.assertEqual(len(probe.probe(opener=supported)), 3)
            self.assertTrue(all(
                headers.get("mcp-protocol-version") == negotiated
                for _, headers in supported.calls[1:]
            ))
        opener = FakeOpener(fault=("tools/list", "paged"))
        self.assertEqual(len(probe.probe(opener=opener)), 3)
        tools_calls = [
            body for body, _ in opener.calls if body["method"] == "tools/list"
        ]
        self.assertEqual(
            [body.get("params") for body in tools_calls],
            [{}, {"cursor": "opaque.cursor"}],
        )
        self.assertEqual([body["id"] for body in tools_calls], [2, 3])
        self.assertEqual(
            [body["id"] for body, _ in opener.calls[-2:]], [4, 5],
        )

    def test_deep_json_nesting_returns_sanitized_probe_error(self):
        # The decoder's concrete recursion threshold varies by CPython
        # version. Inject the exact failure at the decode boundary so this
        # regression deterministically proves it cannot escape as a traceback.
        payload = b'{"jsonrpc":"2.0","id":1,"result":{"sensitive":"do not print"}}'
        with patch.object(probe.json, "loads", side_effect=RecursionError("secret")):
            with self.assertRaisesRegex(probe.ProbeError, "malformed JSON") as exc:
                probe._extract_message(payload, "application/json", 1)
        self.assertNotIn("sensitive", str(exc.exception))
        self.assertNotIn("secret", str(exc.exception))

    def test_sse_trickling_without_newline_hits_total_deadline(self):
        # A socket idle timeout is NOT a total deadline. Simulate a blocked
        # chunk read from a server that keeps its stream open indefinitely.
        class SlowNoNewlineResponse(FakeResponse):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.finished_read = False

            def read1(self, limit):
                del limit
                time.sleep(0.2)
                self.finished_read = True
                return b"x"

            def readline(self, limit=-1):
                raise AssertionError("SSE probe must never use readline")

        opener = FakeOpener()
        regular_open = opener.open
        slow_responses = []

        def trickling_open(request, *, timeout):
            if json.loads(request.data)["method"] == "tools/list":
                slow = SlowNoNewlineResponse(
                    b"data: not-a-complete-event",
                    content_type="text/event-stream",
                )
                slow_responses.append(slow)
                return slow
            return regular_open(request, timeout=timeout)

        opener.open = trickling_open
        with patch.object(probe, "RESPONSE_DEADLINE_SECONDS", 0.05):
            with self.assertRaisesRegex(probe.ProbeError, "time limit"):
                probe.probe(opener=opener)
        self.assertEqual(len(slow_responses), 1)
        self.assertFalse(
            slow_responses[0].finished_read,
            "the deadline did not interrupt the blocking response read",
        )

    def test_slow_response_headers_respect_total_deadline(self):
        # A server that trickles headers must not bypass the response timer.
        opener = FakeOpener()
        regular_open = opener.open
        reached_after_sleep = []

        def slow_headers(request, *, timeout):
            if json.loads(request.data)["method"] == "tools/list":
                time.sleep(0.2)
                reached_after_sleep.append(True)
            return regular_open(request, timeout=timeout)

        opener.open = slow_headers
        with patch.object(probe, "RESPONSE_DEADLINE_SECONDS", 0.05):
            with self.assertRaisesRegex(probe.ProbeError, "time limit"):
                probe.probe(opener=opener)
        self.assertEqual(
            reached_after_sleep, [],
            "the hard deadline did not interrupt slow response headers",
        )

    def test_fragmented_sse_crlf_across_reads(self):
        opener = FakeOpener()
        regular_open = opener.open

        def fragmented_open(request, *, timeout):
            response = regular_open(request, timeout=timeout)
            if json.loads(request.data)["method"] == "tools/list":
                # Exercise actual CRLF, with CR and LF delivered separately.
                # The old fixture only transmitted LF despite its name.
                response.value = response.value.replace(b"\n", b"\r\n")
                response.read1 = lambda limit: FakeResponse.read1(response, min(limit, 1))
            return response

        opener.open = fragmented_open
        self.assertEqual(len(probe.probe(opener=opener)), 3)

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
