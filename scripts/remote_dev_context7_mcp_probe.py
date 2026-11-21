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
TOTAL_TEST_SECONDS = 90  # Shared across /ping and every MCP operation.
EXPECTED_LIBRARY_ID = "/psf/requests"
REQUIRED_TOOLS = frozenset({"resolve-library-id", "query-docs"})


class ProbeError(RuntimeError):
    """Never embed server-supplied payloads or authentication values."""


class NoMatchingReply(ProbeError):
    """A complete SSE frame had no reply for this JSON-RPC request."""


class UnverifiedDocumentation(ProbeError):
    """The tool returned without an explicit error but no verified evidence."""


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
        # A 2025-11-25 resumability priming event can contain "data:"
        # without JSON. It is an SSE frame, NOT the RPC reply.
        if not message.strip():
            continue
        try:
            parsed = json.loads(message)
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProbeError("MCP response contained malformed JSON") from exc
        # bool is an int subclass in Python, but JSON-RPC id:true is not id:1.
        if (isinstance(parsed, dict) and type(parsed.get("id")) is int
                and parsed["id"] == request_id):
            found.append(parsed)
    if not found:
        raise NoMatchingReply("MCP response did not contain a matching request ID")
    if len(found) > 1:
        raise ProbeError("MCP response contained duplicate replies for one request ID")
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


def _exchange(opener, *, method: str, request_id: int | None, params: dict | None,
              api_key: str | None, protocol: str, session: str | None,
              overall_deadline: float | None = None):
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
        if overall_deadline is not None:
            deadline = min(deadline, overall_deadline)
        with _hard_read_deadline(deadline - time.monotonic()):
            opened = opener.open(req, timeout=TIMEOUT_SECONDS)
        with opened as response:
            final = urlparse(response.geturl())
            if (final.scheme, final.hostname, final.path, final.query, final.fragment) != (
                    "https", "mcp.context7.com", "/mcp", "", ""):
                raise ProbeError("MCP request resolved to an unexpected host or path")
            status = response.status
            assigned_session = response.headers.get("Mcp-Session-Id")
            if assigned_session is not None:
                if (not isinstance(assigned_session, str) or
                        not 1 <= len(assigned_session) <= 128 or
                        not re.fullmatch(r"[\x21-\x7e]+", assigned_session) or
                        (api_key is not None and api_key in assigned_session)):
                    raise ProbeError("MCP server provided an unsafe session identifier")
                # Only initialize may establish the session; do not let later
                # responses rewrite an ID that will become an HTTP header.
                if method != "initialize" and assigned_session != session:
                    raise ProbeError("MCP server changed the established session")
            next_session = assigned_session if method == "initialize" else session
            if request_id is None:
                if status != 202:
                    raise ProbeError("MCP notification was not accepted with HTTP 202")
                # The transport requires HTTP 202 with NO body. Read one byte
                # under the remaining budget; never accept a hidden error body.
                with _hard_read_deadline(deadline - time.monotonic()):
                    unexpected = response.read1(1)
                if unexpected:
                    raise ProbeError("MCP notification returned an unexpected body")
                return {}, next_session
            if status != 200:
                raise ProbeError("MCP request failed with HTTP status " + str(status))
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].lower().strip() == "text/event-stream":
                # Read bounded chunks instead of readline(), which a server
                # trickling bytes without a newline could keep open indefinitely.
                # Recognize only complete SSE frames before parsing JSON.
                # Parse CR, LF and CRLF as lines incrementally. A trailing CR
                # terminates its line immediately, even on an OPEN stream.
                # If the next fragment begins with LF, consume it as part of
                # the preceding CRLF rather than a new blank line.
                frame = bytearray()
                line = bytearray()
                after_cr = False
                received = 0
                while received <= MAX_RESPONSE_BYTES:
                    with _hard_read_deadline(deadline - time.monotonic()):
                        chunk = response.read1(min(8192, MAX_RESPONSE_BYTES - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > MAX_RESPONSE_BYTES:
                        raise ProbeError("MCP response exceeded its size limit")
                    for char in chunk:
                        if after_cr:
                            after_cr = False
                            if char == 10:
                                continue
                        if char in (10, 13):
                            is_blank = not line
                            frame.extend(line)
                            frame.extend(b"\n")
                            line.clear()
                            after_cr = char == 13
                            if is_blank:
                                try:
                                    parsed = _extract_message(
                                        bytes(frame), content_type, request_id)
                                except NoMatchingReply:
                                    # An SSE priming/event frame or an unrelated
                                    # JSON-RPC message is not this RPC's result.
                                    frame.clear()
                                else:
                                    return parsed, next_session
                        else:
                            line.append(char)
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


def _tool_text(result: dict) -> str:
    """Only treat text content as evidence when the MCP tool did not fail."""
    if result.get("isError") not in (None, False):
        return ""
    content = result.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        item["text"] for item in content
        if isinstance(item, dict) and item.get("type") == "text"
        and isinstance(item.get("text"), str)
    ).strip()


def _has_public_content(result: dict, *, method: str,
                        raise_on_failure: bool = False) -> bool:
    text = _tool_text(result)
    if not text:
        return False
    # Tool output may echo our question before the actual result. Never
    # count echoed questions as positive evidence, or overlook a subsequent
    # 'No documentation found' / quota / unauthorized status line.
    lines = text.splitlines()
    substantive = []
    failed = False
    failure_status = ""
    in_fence = False
    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            in_fence = not in_fence
            substantive.append(raw)
            continue
        if not line:
            continue
        if not in_fence and re.match(r"^#{1,6}\s+", line):
            # Markdown status headings are service failures, not documentation.
            # An example comment such as "# request failed after ..." is not
            # an unambiguous status heading; preserve legitimate examples.
            heading = re.sub(r"^#{1,6}\s+", "", line).strip().rstrip("#").strip()
            if re.match(
                r"(?i)^(?:(?:error|warning|status)\s*[:\-]\s*)?"
                r"(?:no (?:matching\s+)?(?:libraries|docs|documentation|results|"
                r"code snippets?|context)(?:\s+(?:were\s+)?found)?"
                r"|rate\s*limit(?:\s+exceeded|ed)|quota exceeded"
                r"|too many requests|unauthorized|authentication required"
                r"|upgrade your plan|service unavailable"
                r"|request failed(?=$|[.!:\-]))",
                heading,
            ):
                failed = True
                failure_status = heading
                break
        if in_fence or line.startswith(("#", ">", "-", "*")):
            # Code examples and quoted documentation are not service status.
            substantive.append(raw)
            continue
        if re.match(r"(?i)^(?:query|question|search(?:\s+query)?)\s*:", line):
            continue
        if re.match(
            r"(?i)^(?:(?:error|warning|status)\s*[:\-]\s*)?"
            r"(?:no (?:matching\s+)?(?:libraries|docs|documentation|results|"
            r"code snippets?|context)(?:\s+(?:were\s+)?found)?"
            r"|rate\s*limit(?:\s+exceeded|ed)?|quota exceeded"
            r"|too many requests|unauthorized|authentication required"
            r"|upgrade your plan|request failed|service unavailable"
            r"|(?:could not|cannot|unable to|failed to)\s+"
            r"(?:retrieve|fetch|find|load|resolve|query|get)\b)",
            line,
        ):
            failed = True
            failure_status = line
            break
        substantive.append(raw)
    if failed:
        # A missing document cannot establish a service outage; keep it
        # UNVERIFIED. Only explicit quota/auth/network failures are FAILED.
        explicit_service_error = re.match(
            r"(?i)^(?:(?:error|warning|status)\s*[:\-]\s*)?"
            r"(?:rate\s*limit(?:\s+exceeded|ed)?|quota exceeded|"
            r"too many requests|unauthorized|authentication required|"
            r"upgrade your plan|request failed|service unavailable)",
            failure_status,
        ) is not None
        if raise_on_failure and explicit_service_error:
            raise ProbeError("Context7 " + method + " tool reported an explicit service failure")
        return False
    if not substantive:
        return False
    text = "\n".join(substantive)
    if method == "resolve-library-id":
        return (
            "Available Libraries:" in text
            and re.search(
                r"(?<![\w/.-])" + re.escape(EXPECTED_LIBRARY_ID) +
                r"(?![\w/.-])", text,
            ) is not None
        )
    if method == "query-docs":
        # Generic Markdown code fences prove nothing: even an error message
        # can quote a snippet. Accept relevant Python Requests prose or a
        # credible Requests code/documentation marker together with timeout.
        if not re.search(r"(?i)\brequests\b", text) or not re.search(
            r"(?i)\btimeouts?\b", text
        ):
            return False
        return (
            re.search(
                r"(?i)\brequests\.(?:get|post|put|patch|delete|head|"
                r"options|request|session)\s*\(", text,
            ) is not None
            or re.search(
                r"(?i)https?://(?:www\.)?(?:requests\.readthedocs\.io|"
                r"github\.com/psf/requests)\b", text,
            ) is not None
            or re.search(
                r"(?is)\b(?:python\s+)?requests\b[^.!?\n]{0,120}"
                r"\b(?:set|specify|pass|configure|use|provide|accepts?)\b"
                r"[^.!?\n]{0,90}\btimeout\b", text,
            ) is not None
            or re.search(
                r"(?is)\b(?:set|specify|pass|configure|use)\b"
                r"[^.!?\n]{0,90}\btimeout\b"
                r"[^.!?\n]{0,100}\brequests\b", text,
            ) is not None
        )
    return False


def _valid_tool_descriptor(tool: object) -> bool:
    if not isinstance(tool, dict):
        return False
    schema = tool.get("inputSchema")
    return (
        isinstance(tool.get("name"), str)
        and isinstance(schema, dict)
        and schema.get("type") == "object"
        and isinstance(schema.get("properties", {}), dict)
    )


def probe(
    api_key: str | None = None, *, opener=None,
    deadline: float | None = None,
) -> tuple[str, ...]:
    """Prove the hosted MCP protocol and two public tool calls; no local writes.

    An empty/absent key uses anonymous access. Native agent and AGY OAuth
    authentication require separate agent-side verification.
    """
    client = _open_client() if opener is None else opener
    # The same monotonic deadline may begin at the caller's /ping. Per
    # request, _exchange additionally enforces RESPONSE_DEADLINE_SECONDS.
    deadline = min(
        time.monotonic() + TOTAL_TEST_SECONDS,
        deadline if deadline is not None else float("inf"),
    )
    session = None
    result, session = _exchange(
        client, method="initialize", request_id=1,
        params={"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "remote-dev-context7-probe", "version": "1.0.0"}},
        api_key=api_key, protocol=PROTOCOL_VERSION, session=session,
        overall_deadline=deadline)
    protocol = result.get("protocolVersion")
    if not isinstance(protocol, str) or protocol not in SUPPORTED_PROTOCOL_VERSIONS:
        raise ProbeError("MCP initialization negotiated an unsupported protocol version")
    capabilities = result.get("capabilities")
    server = result.get("serverInfo")
    if (not isinstance(capabilities, dict)
            or not isinstance(capabilities.get("tools"), dict)
            or not isinstance(server, dict)
            or not all(isinstance(server.get(k), str) and server[k].strip()
                       for k in ("name", "version"))):
        raise ProbeError("MCP initialization lacked tool capability or server information")
    _, session = _exchange(client, method="notifications/initialized",
                           request_id=None, params=None, api_key=api_key,
                           protocol=protocol, session=session,
                           overall_deadline=deadline)
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
            params=params, api_key=api_key, protocol=protocol, session=session,
            overall_deadline=deadline)
        tools = listed.get("tools")
        if not isinstance(tools, list):
            raise ProbeError("MCP tools/list returned invalid tools")
        found_tools.update(
            item["name"] for item in tools if _valid_tool_descriptor(item))
        if REQUIRED_TOOLS.issubset(found_tools):
            break
        cursor = listed.get("nextCursor")
        if cursor is None:
            raise ProbeError("MCP tools/list did not expose both required Context7 tools")
        if (not isinstance(cursor, str) or not cursor or len(cursor) > 256
                or any(ord(ch) < 32 or ord(ch) == 127 for ch in cursor)
                or (api_key is not None and api_key in cursor)
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
            protocol=protocol, session=session, overall_deadline=deadline)
        if response.get("isError") not in (None, False):
            raise ProbeError("Context7 " + name + " tool returned an explicit error")
        if not _has_public_content(
                response, method=name, raise_on_failure=True):
            raise UnverifiedDocumentation(
                "Context7 " + name + " documentation UNVERIFIED (no positive evidence)"
            )
    return (
        "Context7 MCP protocol initialize: PASS",
        "Context7 MCP tools/list: PASS (resolve-library-id, query-docs)",
        "Context7 MCP real tools/call: PASS (2 public documentation calls)",
    )
