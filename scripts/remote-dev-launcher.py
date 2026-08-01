#!/usr/bin/env python3
"""Serve the fixed Remote Dev launcher without relaying agent traffic."""

from __future__ import annotations

import base64
import binascii
import hmac
import html
import json
import os
import re
import secrets
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

_SAFE_HOST = re.compile(r"^[A-Za-z0-9.:[\]_-]+$")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if raw == "1":
        return True
    if raw == "0":
        return False
    raise ValueError(f"{name} must be 0 or 1")


def _env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return value


def _normalize_path(name: str, value: str) -> str:
    if not _SAFE_PATH.fullmatch(value):
        raise ValueError(
            f"{name} must be an absolute URL path containing only RFC 3986 path characters"
        )
    if value != "/":
        value = value.rstrip("/")
    return value


def _optional_host(name: str, value: str) -> str:
    if value == "":
        return value
    if not _SAFE_HOST.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")
    if "/" in value or "@" in value or any(character.isspace() for character in value):
        raise ValueError(f"{name} must be a host or IP address without a scheme or path")
    return value


def _optional_scheme(name: str, value: str) -> str:
    if value not in ("", "http", "https"):
        raise ValueError(f"{name} must be empty, http or https")
    return value


def _read_password() -> str | None:
    password_file = os.environ.get("WEB_PASSWORD_FILE", "")
    password = os.environ.get("WEB_PASSWORD", "")

    if password_file:
        try:
            password = Path(password_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"WEB_PASSWORD_FILE is not readable: {password_file}") from exc
        password = password.rstrip("\r\n")

    if password:
        if "\r" in password or "\n" in password:
            raise ValueError("web password must be a single line")
        return password

    if _env_bool("ALLOW_INSECURE_WEB", False):
        return None

    raise ValueError(
        "web authentication is not configured; set WEB_PASSWORD_FILE or WEB_PASSWORD"
    )


@dataclass(frozen=True)
class LauncherConfig:
    bind: str
    port: int
    base_path: str
    username: str
    password: str | None
    check_origin: bool
    codex_host: str
    codex_port: int
    codex_scheme: str
    codex_path: str
    image_version: str
    source_revision: str

    @property
    def page_paths(self) -> frozenset[str]:
        if self.base_path == "/":
            return frozenset(("/",))
        return frozenset((self.base_path, f"{self.base_path}/"))

    @property
    def health_path(self) -> str:
        if self.base_path == "/":
            return "/healthz"
        return f"{self.base_path}/healthz"


def _read_metadata(path: str, fallback: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return fallback
    return value or fallback


def load_config() -> LauncherConfig:
    username = os.environ.get("WEB_USERNAME", "remote-dev")
    if not username or ":" in username or "\r" in username or "\n" in username:
        raise ValueError("WEB_USERNAME must be a non-empty single-line value without colon")

    return LauncherConfig(
        bind=os.environ.get("WEB_BIND", "0.0.0.0"),
        port=_env_port("WEB_PORT", 7680),
        base_path=_normalize_path("WEB_BASE_PATH", os.environ.get("WEB_BASE_PATH", "/")),
        username=username,
        password=_read_password(),
        check_origin=_env_bool("WEB_CHECK_ORIGIN", True),
        codex_host=_optional_host(
            "REMOTE_DEV_LAUNCHER_CODEX_HOST",
            os.environ.get("REMOTE_DEV_LAUNCHER_CODEX_HOST", ""),
        ),
        codex_port=_env_port("REMOTE_DEV_LAUNCHER_CODEX_PORT", 7681),
        codex_scheme=_optional_scheme(
            "REMOTE_DEV_LAUNCHER_CODEX_SCHEME",
            os.environ.get("REMOTE_DEV_LAUNCHER_CODEX_SCHEME", ""),
        ),
        codex_path=_normalize_path(
            "REMOTE_DEV_LAUNCHER_CODEX_PATH",
            os.environ.get("REMOTE_DEV_LAUNCHER_CODEX_PATH", "/"),
        ),
        image_version=_read_metadata(
            "/usr/share/remote-dev/image-version", "unavailable"
        ),
        source_revision=_read_metadata(
            "/usr/share/remote-dev/source-revision", "unavailable"
        ),
    )


def build_page(config: LauncherConfig, nonce: str) -> bytes:
    route_config = json.dumps(
        {
            "host": config.codex_host,
            "port": config.codex_port,
            "scheme": config.codex_scheme,
            "path": config.codex_path,
        },
        separators=(",", ":"),
    )
    version = html.escape(config.image_version)
    revision = html.escape(config.source_revision)
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Remote Dev</title>
<style nonce="{nonce}">
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: Canvas; color: CanvasText; }}
main {{ width: min(42rem, calc(100% - 2rem)); padding: 2rem; border: 1px solid GrayText; border-radius: 1rem; }}
h1 {{ margin-top: 0; }}
a {{ display: inline-block; margin-top: 1rem; padding: .8rem 1rem; border: 1px solid LinkText; border-radius: .6rem; font-weight: 700; }}
small {{ display: block; margin-top: 1.5rem; opacity: .75; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<main>
<h1>Remote Dev</h1>
<p>Select an available isolated agent service.</p>
<a id="codex-link" href="#">Open Codex</a>
<p>The Codex terminal authenticates independently and runs in a separate container.</p>
<small>Image {version} · Source {revision}</small>
</main>
<script nonce="{nonce}">
const config = {route_config};
const host = config.host || window.location.hostname;
const scheme = config.scheme || window.location.protocol.replace(':', '');
const formattedHost = host.includes(':') && !host.startsWith('[') ? `[${{host}}]` : host;
document.getElementById('codex-link').href = `${{scheme}}://${{formattedHost}}:${{config.port}}${{config.path}}`;
</script>
</body>
</html>
"""
    return document.encode("utf-8")


class LauncherServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        super().__init__((config.bind, config.port), LauncherHandler)


class LauncherHandler(BaseHTTPRequestHandler):
    server: LauncherServer
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format_string: str, *args: object) -> None:
        sys.stderr.write(
            "%s - - [%s] %s\n"
            % (self.client_address[0], self.log_date_time_string(), format_string % args)
        )

    def _security_headers(self, nonce: str | None = None) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        if nonce is None:
            policy = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        else:
            policy = (
                "default-src 'none'; "
                f"style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        self.send_header("Content-Security-Policy", policy)

    def _respond(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        nonce: str | None = None,
        challenge: bool = False,
        send_body: bool = True,
    ) -> None:
        self.send_response(status)
        self._security_headers(nonce)
        if challenge:
            self.send_header(
                "WWW-Authenticate", 'Basic realm="Remote Dev Launcher", charset="UTF-8"'
            )
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _authorized(self) -> bool:
        config = self.server.config
        if config.password is None:
            return True

        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True)
        except binascii.Error:
            return False
        username, separator, password = decoded.partition(b":")
        if not separator:
            return False
        return hmac.compare_digest(
            username, config.username.encode("utf-8")
        ) and hmac.compare_digest(password, config.password.encode("utf-8"))

    def _origin_allowed(self) -> bool:
        if not self.server.config.check_origin:
            return True
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host", "")
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        if parsed.username is not None or parsed.password is not None:
            return False

        normalized_host = host.lower()
        normalized_origin = parsed.netloc.lower()
        if not _SAFE_HOST.fullmatch(normalized_host):
            return False
        if not _SAFE_HOST.fullmatch(normalized_origin):
            return False
        return hmac.compare_digest(
            normalized_origin.encode("ascii"), normalized_host.encode("ascii")
        )

    def _serve(self, *, send_body: bool) -> None:
        path = urlsplit(self.path).path
        config = self.server.config

        if path == config.health_path:
            body = b'{"role":"launcher","status":"ok"}\n'
            self._respond(
                HTTPStatus.OK,
                body,
                "application/json; charset=utf-8",
                send_body=send_body,
            )
            return

        if path not in config.page_paths:
            self._respond(
                HTTPStatus.NOT_FOUND,
                b"Not found\n",
                "text/plain; charset=utf-8",
                send_body=send_body,
            )
            return

        if not self._authorized():
            self._respond(
                HTTPStatus.UNAUTHORIZED,
                b"Authentication required\n",
                "text/plain; charset=utf-8",
                challenge=True,
                send_body=send_body,
            )
            return

        if not self._origin_allowed():
            self._respond(
                HTTPStatus.FORBIDDEN,
                b"Origin rejected\n",
                "text/plain; charset=utf-8",
                send_body=send_body,
            )
            return

        nonce = secrets.token_urlsafe(18)
        body = build_page(config, nonce)
        self._respond(
            HTTPStatus.OK,
            body,
            "text/html; charset=utf-8",
            nonce=nonce,
            send_body=send_body,
        )

    def do_GET(self) -> None:  # noqa: N802
        self._serve(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(send_body=False)

    def _method_not_allowed(self) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self._security_headers()
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed


def main() -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(
        f"Remote Dev launcher listening on {config.bind}:{config.port}{config.base_path}",
        file=sys.stderr,
        flush=True,
    )
    with LauncherServer(config) as server:
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
