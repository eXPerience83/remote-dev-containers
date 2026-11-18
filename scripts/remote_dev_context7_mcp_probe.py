#!/usr/bin/env python3
"""Bounded, read-only-local Context7 Streamable HTTP MCP functional probe.

The only remote operations are public documentation lookups explicitly initiated
from a menu test. This does NOT prove that Codex or Antigravity called a tool.
The caller owns authentication: Codex may provide its validated API key;
Antigravity must NOT read or forward the vendor's private OAuth state.
"""
from __future__ import annotations

import json
import re
from http.client import HTTPException
import signal
import ssl
import threading
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

ENDPOINT = "https://mcp.context7.com/mcp"
MAX_RESPONSE_BYTES = 128 * 1024
TIMEOUT_SECONDS = 12
RESPONSE_DEADLINE_SECONDS = 25
PROTOCOL_VERSION = "2025-03-26"
# These 2025 revisions retain the Streamable HTTP initialize/list/call
# semantics exercised by this probe. Later revisions require a separate
# compatibility review before advertising support.
SUPPORTED_PROTOCOL_VERSIONS = frozenset({
    "2025-03-26", "2025-06-18", "2025-11-25",
})
MAX_TOOL_PAGES = 6
REQUIRED_TOOLS = frozenset({"resolve-library-id", "query-docs"})


class ProbeError(RuntimeError):
    """Never embed server-supplied payloads or authentication values."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProbeError("MCP transport refused an HTTP redirect")


def _open_client():
    # A user-configured proxy must never receive the private Codex API key.
    return build_opener(ProxyHandler({}), HTTPSHandler(context=ssl.create_default_context()), NoRedirect())


def _extract_message(raw: bytes, content_type: str, request_id: int) -> dict:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProbeError("MCP response exceeded its size limit")
    mime = content_type.split(";", 1)[0].lower().strip()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProbeError("MCP response was not UTF-8") from exc
    if mime == "application/json":
        messages = [text]
    elif mime == "text/event-stream":
        messages = []
        current = []
        # SSE separators are CR, LF and CRLF only; Python str.splitlines()
        # would also split a literal U+2028 inside a valid JSON data string.
        for line in re.split(r"\r\n|\r|\n", text):
            if line.startswith("data:"):
                current.append(line[5:].lstrip(" "))
            elif line == "" and current:
                messages.append("\n".join(current))
                current = []
        if current:
            messages.append("\n".join(current))
    else:
        raise ProbeError("MCP response used an unexpected content type")
    found = []
    for message in messages:
        try:
            parsed = json.loads(message)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProbeError("MCP response contained malformed JSON") from exc
        if isinstance(parsed, dict) and parsed.get("id") == request_id:
            found.append(parsed)
    if len(found) != 1:
        raise ProbeError("MCP response did not contain exactly one matching request ID")
    reply = found[0]
    if reply.get("jsonrpc") != "2.0" or "error" in reply or not isinstance(reply.get("result"), dict):
        raise ProbeError("MCP request was rejected or returned an invalid result")
    return reply["result"]


@contextmanager
def _hard_read_deadline(remaining: float):
    """Bound a single buffered TLS read even if the server trickles bytes.

    Socket timeouts are idle timeouts; a stream sending one byte before each
    timeout can keep readline/read1 blocked past our total deadline. Remote
    Dev invokes this synchronous probe on Linux from its main CLI thread.
    """
    if remaining <= 0:
        raise ProbeError("MCP response exceeded its time limit")
    if not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        raise ProbeError("MCP deadline enforcement is unavailable in this execution context")
    previous = signal.getitimer(signal.ITIMER_REAL)
    if previous[0] > 0:
        raise ProbeError("MCP probe cannot replace an existing process alarm")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def alarm_handler(signum, frame):
        del signum, frame
        raise ProbeError("MCP response exceeded its time limit")

    try:
        signal.signal(signal.SIGALRM, alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, remaining)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _completed_sse_prefix(raw: bytes) -> bytes | None:
    """Return complete SSE frames only, retaining incomplete trailing bytes."""
    last_boundary = 0
    offset = 0
    # Parse only SSE's CR, LF and CRLF line delimiters. The regex must
    # never treat UTF-8 U+2028 or other bytes as event boundaries.
    for match in re.finditer(rb"[^\r\n]*(?:\r\n|\r|\n)", raw):
        offset = match.end()
        if match.group(0) in (b"\n", b"\r", b"\r\n"):
            last_boundary = offset
    return raw[:last_boundary] if last_boundary else None


def _exchange(opener, *, method: str, request_id: int | None, params: dict | None,
              api_key: str | None, protocol: str, session: str | None):
    request = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        request["id"] = request_id
    if params is not None:
        request["params"] = params
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": protocol,
        "User-Agent": "remote-dev-context7-mcp-probe/1",
    }
    if api_key is not None:
        if (not isinstance(api_key, str) or not 1 <= len(api_key) <= 16384 or
                any(not 33 <= ord(char) <= 126 for char in api_key)):
            raise ProbeError("validated Context7 API key has an unsafe header shape")
        headers["CONTEXT7_API_KEY"] = api_key
    if session:
        headers["Mcp-Session-Id"] = session
    req = Request(ENDPOINT, data=json.dumps(request, separators=(",", ":")).encode("utf-8"),
                  headers=headers, method="POST")
    try:
        # A socket timeout is only an idle timeout. Include slow response
        # headers in the same hard deadline used for SSE and JSON body reads.
        deadline = time.monotonic() + RESPONSE_DEADLINE_SECONDS
        with _hard_read_deadline(deadline - time.monotonic()):
            opened = opener.open(req, timeout=TIMEOUT_SECONDS)
        with opened as response:
            final = urlparse(response.geturl())
            if (final.scheme, final.hostname, final.path, final.query, final.fragment) != (
                    "https", "mcp.context7.com", "/mcp", "", ""):
                raise ProbeError("MCP request resolved to an unexpected host or path")
            status = response.status
            next_session = response.headers.get("Mcp-Session-Id") or session
            if next_session and (not isinstance(next_session, str) or len(next_session) > 128 or
                                 not re.fullmatch(r"[\x21-\x7e]+", next_session)):
                raise ProbeError("MCP server provided an unsafe session identifier")
            if request_id is None:
                if status not in (200, 202, 204):
                    raise ProbeError("MCP initialization notification was rejected")
                # Notifications have no JSON-RPC reply and may be answered
                # by an open stream. Close immediately; never wait for EOF.
                return {}, next_session
            if status != 200:
                raise ProbeError("MCP request failed with HTTP status " + str(status))
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].lower().strip() == "text/event-stream":
                # Read bounded chunks instead of readline(), which a server
                # trickling bytes without a newline could keep open indefinitely.
                # Recognize only complete SSE frames before parsing JSON.
                pending = bytearray()
                scan_at = 0
                line_start = 0
                received = 0
                while received <= MAX_RESPONSE_BYTES:
                    with _hard_read_deadline(deadline - time.monotonic()):
                        chunk = response.read1(min(8192, MAX_RESPONSE_BYTES - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_RESPONSE_BYTES:
                        raise ProbeError("MCP response exceeded its size limit")
                    pending.extend(chunk)
                    # Scan each byte once; CRLF may straddle two chunks.
                    # A whitespace-only field is NOT an empty SSE line.
                    while scan_at < len(pending):
                        char = pending[scan_at]
                        if char not in (10, 13):
                            scan_at += 1
                            continue
                        if char == 13 and scan_at + 1 == len(pending):
                            break
                        end = (scan_at + 2 if char == 13 and pending[scan_at + 1] == 10
                               else scan_at + 1)
                        if scan_at == line_start:
                            frame = bytes(pending[:end])
                            del pending[:end]
                            scan_at = 0
                            line_start = 0
                            try:
                                parsed = _extract_message(frame, content_type, request_id)
                            except ProbeError as exc:
                                if "exactly one matching request ID" not in str(exc):
                                    raise
                            else:
                                return parsed, next_session
                        else:
                            line_start = end
                            scan_at = end
                # A final CR is a legitimate SSE line ending, even without
                # a following LF; do not synthesize an event without a blank.
                if pending and pending[-1] == 13:
                    pending.extend(b"\n")
                    complete = _completed_sse_prefix(bytes(pending))
                    if complete is not None:
                        return _extract_message(complete, content_type, request_id), next_session
                raise ProbeError("MCP event stream did not return the matching request ID")
            # read1 does not wait for the entire requested byte count. This
            # bounds slow-trickling or non-terminating JSON responses too.
            data = bytearray()
            while len(data) <= MAX_RESPONSE_BYTES:
                if time.monotonic() >= deadline:
                    raise ProbeError("MCP response exceeded its time limit")
                with _hard_read_deadline(deadline - time.monotonic()):
                    chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            raw = bytes(data)
    except ProbeError:
        raise
    except HTTPError as exc:
        raise ProbeError("MCP request failed with HTTP status " + str(exc.code)) from None
    except (OSError, URLError, HTTPException, TimeoutError, ValueError) as exc:
        raise ProbeError("MCP connection failed (" + type(exc).__name__ + ")") from None
    return _extract_message(raw, content_type, request_id), next_session


def _has_public_content(result: dict) -> bool:
    if result.get("isError") is True:
        return False
    content = result.get("content")
    return isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "text"
        and isinstance(item.get("text"), str) and bool(item["text"].strip())
        for item in content
    )


def probe(api_key: str | None = None, *, opener=None) -> tuple[str, ...]:
    """Prove the hosted MCP protocol and two public tool calls; no local writes.

    An empty/absent key uses anonymous access. Native agent and AGY OAuth
    authentication require separate agent-side verification.
    """
    client = _open_client() if opener is None else opener
    session = None
    result, session = _exchange(
        client, method="initialize", request_id=1,
        params={"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "remote-dev-context7-probe", "version": "1.0.0"}},
        api_key=api_key, protocol=PROTOCOL_VERSION, session=session)
    protocol = result.get("protocolVersion")
    if not isinstance(protocol, str) or protocol not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProbeError("MCP initialization negotiated an unsupported protocol version")
    _, session = _exchange(client, method="notifications/initialized",
                           request_id=None, params=None, api_key=api_key,
                           protocol=protocol, session=session)
    # tools/list is paginated. Bound both total pages and repeated cursors,
    # and keep JSON-RPC request IDs unique across all pages and tool calls.
    found_tools: set[str] = set()
    cursor = None
    visited_cursors: set[str] = set()
    request_id = 2
    for _page in range(MAX_TOOL_PAGES):
        params = {} if cursor is None else {"cursor": cursor}
        listed, session = _exchange(
            client, method="tools/list", request_id=request_id,
            params=params, api_key=api_key, protocol=protocol, session=session)
        tools = listed.get("tools")
        if not isinstance(tools, list):
            raise ProbeError("MCP tools/list returned invalid tools")
        found_tools.update(
            item["name"] for item in tools if isinstance(item, dict)
            and isinstance(item.get("name"), str))
        if REQUIRED_TOOLS.issubset(found_tools):
            break
        cursor = listed.get("nextCursor")
        if cursor is None:
            raise ProbeError("MCP tools/list did not expose both required Context7 tools")
        if (not isinstance(cursor, str) or not cursor or len(cursor) > 256
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in cursor)
                or cursor in visited_cursors):
            raise ProbeError("MCP tools/list returned an unsafe or repeated cursor")
        visited_cursors.add(cursor)
        request_id += 1
    else:
        raise ProbeError("MCP tools/list exceeded the page limit")
    for request_id, name, arguments in (
        (request_id + 1, "resolve-library-id",
         {"libraryName": "Requests", "query": "Python Requests HTTP documentation"}),
        (request_id + 2, "query-docs",
         {"libraryId": "/psf/requests", "query": "How do I set a timeout on a GET request?"}),
    ):
        response, session = _exchange(
            client, method="tools/call", request_id=request_id,
            params={"name": name, "arguments": arguments}, api_key=api_key,
            protocol=protocol, session=session)
        if not _has_public_content(response):
            raise ProbeError("Context7 " + name + " tool returned no usable documentation")
    return (
        "Context7 MCP protocol initialize: PASS",
        "Context7 MCP tools/list: PASS (resolve-library-id, query-docs)",
        "Context7 MCP real tools/call: PASS (2 public documentation calls)",
    )
