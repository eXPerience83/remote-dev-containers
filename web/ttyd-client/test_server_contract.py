#!/usr/bin/env python3
"""Exercise ttyd authentication, origin, base-path, and max-client behavior."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPBasicAuthHandler, HTTPPasswordMgrWithDefaultRealm, build_opener


EXPECTED_SHA = "aafc89fde6e1f805d1c78ac49caf41977cb85bf900ba84c108eb57419a6a0a48"


def websocket(url: str, username: str, password: str, origin: str) -> tuple[socket.socket, bytes]:
    parsed = urlsplit(url)
    sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=5)
    credential = base64.b64encode(f"{username}:{password}".encode()).decode()
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {parsed.path} HTTP/1.1\r\nHost: {parsed.netloc}\r\n"
        f"Authorization: Basic {credential}\r\nOrigin: {origin}\r\n"
        "Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Protocol: tty\r\n\r\n"
    )
    sock.sendall(request.encode())
    response = sock.recv(4096)
    return sock, response


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--username", default="synthetic")
    parser.add_argument("--password", default="synthetic-password")
    args = parser.parse_args()
    base = args.url.rstrip("/")
    parsed = urlsplit(base)

    try:
        build_opener().open(base + "/", timeout=5)
        raise SystemExit("ERROR: unauthenticated ttyd request succeeded")
    except HTTPError as error:
        if error.code != 401:
            raise

    manager = HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, base, args.username, args.password)
    opener = build_opener(HTTPBasicAuthHandler(manager))
    html = opener.open(base + "/", timeout=5).read()
    if hashlib.sha256(html).hexdigest() != EXPECTED_SHA or b"remoteDevExtensions" not in html:
        raise SystemExit("ERROR: ttyd did not serve the verified Remote Dev client")
    token = opener.open(base + "/token", timeout=5).read()
    if b"token" not in token:
        raise SystemExit("ERROR: authenticated token endpoint returned an invalid response")

    valid_origin = f"{parsed.scheme}://{parsed.netloc}"
    rejected, response = websocket(base + "/ws", args.username, args.password, "http://invalid.example")
    rejected.close()
    if response.startswith(b"HTTP/1.1 101"):
        raise SystemExit("ERROR: ttyd accepted a mismatched WebSocket Origin")

    first, response = websocket(base + "/ws", args.username, args.password, valid_origin)
    if not response.startswith(b"HTTP/1.1 101"):
        raise SystemExit(f"ERROR: valid WebSocket upgrade failed: {response[:80]!r}")
    second, response = websocket(base + "/ws", args.username, args.password, valid_origin)
    second.close()
    first.close()
    if response.startswith(b"HTTP/1.1 101"):
        raise SystemExit("ERROR: ttyd exceeded the configured one-client limit")
    print("Remote Dev ttyd server/client contract: OK")


if __name__ == "__main__":
    main()
