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
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

ENDPOINT = "https://mcp.context7.com/mcp"
MAX_RESPONSE_BYTES = 128 * 1024
TIMEOUT_SECONDS = 12
PROTOCOL_VERSION = "2025-03-26"
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
        for line in text.splitlines():
            if line.startswith("data:"):
                current.append(line[5:].lstrip(" "))
            elif not line.strip() and current:
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
        except (ValueError, TypeError) as exc:
            raise ProbeError("MCP response contained malformed JSON") from exc
        if isinstance(parsed, dict) and parsed.get("id") == request_id:
            found.append(parsed)
    if len(found) != 1:
        raise ProbeError("MCP response did not contain exactly one matching request ID")
    reply = found[0]
    if reply.get("jsonrpc") != "2.0" or "error" in reply or not isinstance(reply.get("result"), dict):
        raise ProbeError("MCP request was rejected or returned an invalid result")
    return reply["result"]


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
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            final = urlparse(response.geturl())
            if (final.scheme, final.hostname, final.path, final.query, final.fragment) != (
                    "https", "mcp.context7.com", "/mcp", "", ""):
                raise ProbeError("MCP request resolved to an unexpected host or path")
            status = response.status
            next_session = response.headers.get("Mcp-Session-Id") or session
            if next_session and (len(next_session) > 128 or
                                 not re.fullmatch(r"[A-Za-z0-9_-]+", next_session)):
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
            deadline = time.monotonic() + 25
            if content_type.split(";", 1)[0].lower().strip() == "text/event-stream":
                # A compliant SSE response may remain open after the matching
                # JSON-RPC event. Read bounded frames, not until connection EOF.
                raw_parts = []
                received = 0
                while received <= MAX_RESPONSE_BYTES:
                    if time.monotonic() >= deadline:
                        raise ProbeError("MCP event stream exceeded its time limit")
                    line = response.readline(MAX_RESPONSE_BYTES - received + 1)
                    if not line:
                        break
                    received += len(line)
                    raw_parts.append(line)
                    if not line.strip() and any(part.startswith(b"data:") for part in raw_parts):
                        try:
                            parsed = _extract_message(
                                b"".join(raw_parts), content_type, request_id)
                        except ProbeError as exc:
                            if "exactly one matching request ID" not in str(exc):
                                raise
                        else:
                            return parsed, next_session
                if received > MAX_RESPONSE_BYTES:
                    raise ProbeError("MCP response exceeded its size limit")
                raise ProbeError("MCP event stream did not return the matching request ID")
            # read1 does not wait for the entire requested byte count. This
            # bounds slow-trickling or non-terminating JSON responses too.
            data = bytearray()
            while len(data) <= MAX_RESPONSE_BYTES:
                if time.monotonic() >= deadline:
                    raise ProbeError("MCP response exceeded its time limit")
                chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            raw = bytes(data)
    except ProbeError:
        raise
    except HTTPError as exc:
        raise ProbeError("MCP request failed with HTTP status " + str(exc.code)) from None
    except (OSError, URLError, TimeoutError, ValueError) as exc:
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
    if not isinstance(protocol, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", protocol):
        raise ProbeError("MCP initialization returned no valid protocol version")
    _, session = _exchange(client, method="notifications/initialized",
                           request_id=None, params=None, api_key=api_key,
                           protocol=protocol, session=session)
    listed, session = _exchange(client, method="tools/list", request_id=2,
                                params={}, api_key=api_key, protocol=protocol, session=session)
    tools = listed.get("tools")
    if not isinstance(tools, list) or not REQUIRED_TOOLS.issubset({
            item.get("name") for item in tools if isinstance(item, dict)
            and isinstance(item.get("name"), str)}):
        raise ProbeError("MCP tools/list did not expose both required Context7 tools")
    for request_id, name, arguments in (
        (3, "resolve-library-id",
         {"libraryName": "Requests", "query": "Python Requests HTTP documentation"}),
        (4, "query-docs",
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
