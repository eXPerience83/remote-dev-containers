#!/usr/bin/env python3
"""Render a compact, validated Google OAuth link for Antigravity in tmux."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

TMUX_BIN = "/usr/bin/tmux"
OAUTH_PREFIX = "https://accounts.google.com/"
OAUTH_END_MARKER = "If you aren't automatically redirected"
MAX_OAUTH_URL_BYTES = 16_384
POLL_INTERVAL_SECONDS = 0.20
READY_FILE_RE = re.compile(r"^\.remote-dev-antigravity-oauth-ready\.[0-9]+$")
PANE_RE = re.compile(r"^%[0-9]+$")
STOP_REQUESTED = False


def validate_oauth_url(url: str) -> str:
    if not url or len(url.encode("utf-8")) > MAX_OAUTH_URL_BYTES:
        raise ValueError("OAuth URL is empty or oversized")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise ValueError("OAuth URL contains control characters")

    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("OAuth URL contains an invalid port") from exc

    if parsed.scheme != "https":
        raise ValueError("OAuth URL must use HTTPS")
    if parsed.hostname != "accounts.google.com":
        raise ValueError("OAuth URL host is not accounts.google.com")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("OAuth URL must not contain user information")
    if port not in (None, 443):
        raise ValueError("OAuth URL uses an unexpected port")
    if not parsed.path.startswith("/o/oauth2/"):
        raise ValueError("OAuth URL uses an unexpected path")
    if not parsed.query:
        raise ValueError("OAuth URL is missing its authorization query")
    if parsed.fragment:
        raise ValueError("OAuth URL must not contain a fragment")

    return url


def extract_oauth_url(capture: str) -> str | None:
    start = capture.rfind(OAUTH_PREFIX)
    if start < 0:
        return None

    end = capture.find(OAUTH_END_MARKER, start)
    if end < 0:
        return None

    candidate = "".join(capture[start:end].split())
    try:
        return validate_oauth_url(candidate)
    except ValueError:
        return None


def validate_pane(pane: str) -> str:
    if not PANE_RE.fullmatch(pane):
        raise ValueError("invalid tmux pane identifier")
    return pane


def capture_pane(pane: str) -> str:
    validate_pane(pane)
    completed = subprocess.run(
        [TMUX_BIN, "capture-pane", "-p", "-J", "-S", "-200", "-t", pane],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=3,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout


def validate_ready_file(path: Path) -> Path:
    if path.parent != Path("/tmp") or not READY_FILE_RE.fullmatch(path.name):
        raise ValueError("invalid OAuth helper readiness path")
    return path


def create_ready_file(path: Path) -> None:
    validate_ready_file(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, b"ready\n")
    finally:
        os.close(fd)


def create_url_file(url: str) -> Path:
    validate_oauth_url(url)
    fd, raw_path = tempfile.mkstemp(
        prefix="remote-dev-antigravity-oauth.",
        dir="/tmp",
        text=False,
    )
    path = Path(raw_path)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, url.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def read_url_file(path: Path) -> str:
    if path.parent != Path("/tmp") or not path.name.startswith(
        "remote-dev-antigravity-oauth."
    ):
        raise ValueError("OAuth URL file is outside the private temporary namespace")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("OAuth URL source is not a regular file")
        if metadata.st_uid != os.geteuid():
            raise ValueError("OAuth URL source has an unexpected owner")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ValueError("OAuth URL source is accessible by another user")
        if metadata.st_size <= 0 or metadata.st_size > MAX_OAUTH_URL_BYTES:
            raise ValueError("OAuth URL source is empty or oversized")
        payload = os.read(fd, MAX_OAUTH_URL_BYTES + 1)
    finally:
        os.close(fd)

    return validate_oauth_url(payload.decode("utf-8", errors="strict"))


def render_popup(url: str, *, wait_for_enter: bool) -> None:
    validate_oauth_url(url)
    link_text = "OPEN GOOGLE SIGN-IN"
    osc8 = f"\033]8;;{url}\033\\{link_text}\033]8;;\033\\"
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("Remote Dev — Antigravity OAuth\n")
    sys.stdout.write("===============================\n\n")
    sys.stdout.write(f"{osc8}\n\n")
    sys.stdout.write(
        "Complete Google authorization in the browser. The browser will show "
        "an authorization code.\n"
    )
    sys.stdout.write(
        "Return here, press Enter to close this popup, then paste the code into "
        "Antigravity.\n\n"
    )
    sys.stdout.write("Press Enter to return to Antigravity... ")
    sys.stdout.flush()
    if wait_for_enter:
        try:
            input()
        except EOFError:
            pass


def show_popup(url_file: Path) -> int:
    command = " ".join(
        [
            shlex.quote(str(Path(__file__).resolve())),
            "popup",
            "--url-file",
            shlex.quote(str(url_file)),
        ]
    )
    completed = subprocess.run(
        [
            TMUX_BIN,
            "display-popup",
            "-E",
            "-w",
            "80%",
            "-h",
            "12",
            "-T",
            "Google OAuth",
            command,
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return completed.returncode


def request_stop(_signum: int, _frame: object) -> None:
    global STOP_REQUESTED
    STOP_REQUESTED = True


def watch(pane: str, ready_file: Path) -> int:
    validate_pane(pane)
    validate_ready_file(ready_file)

    baseline = extract_oauth_url(capture_pane(pane))
    create_ready_file(ready_file)

    while not STOP_REQUESTED:
        current = extract_oauth_url(capture_pane(pane))
        if current is not None and current != baseline:
            url_file = create_url_file(current)
            try:
                return show_popup(url_file)
            finally:
                try:
                    url_file.unlink()
                except FileNotFoundError:
                    pass
        time.sleep(POLL_INTERVAL_SECONDS)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--pane", required=True)
    watch_parser.add_argument("--ready-file", required=True, type=Path)

    popup_parser = subparsers.add_parser("popup")
    popup_parser.add_argument("--url-file", required=True, type=Path)
    popup_parser.add_argument("--no-wait", action="store_true", help=argparse.SUPPRESS)

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--input", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    args = build_parser().parse_args(argv)

    try:
        if args.command == "watch":
            return watch(args.pane, args.ready_file)
        if args.command == "popup":
            render_popup(read_url_file(args.url_file), wait_for_enter=not args.no_wait)
            return 0
        if args.command == "extract":
            source = (
                args.input.read_text(encoding="utf-8", errors="replace")
                if args.input is not None
                else sys.stdin.read()
            )
            url = extract_oauth_url(source)
            if url is None:
                return 1
            print(url)
            return 0
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
