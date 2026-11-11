#!/usr/bin/env python3
"""Bounded Playwright archive download with validated HTTPS redirect hops.

The discovery job and image installer share this implementation. The source
URL is separately pinned/validated by each caller; this module constrains
every subsequent hop before making the next network request.
"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_HOPS = 6
MAX_SECONDS = 740
MAX_BYTES = 600_000_000
COMPONENTS = frozenset(("chromium-headless-shell", "ffmpeg"))


class ArchiveDownloadError(ValueError):
    """Redirect chain or download violates the reviewed source boundary."""


def validate_archive_url(url: str, component: str) -> None:
    if component not in COMPONENTS or not isinstance(url, str):
        raise ArchiveDownloadError("unsupported archive or URL")
    if any(char in url for char in ("\\", "\r", "\n", "\t", "{", "}")):
        raise ArchiveDownloadError("unsafe redirect URL characters")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443)
            or parsed.query or parsed.fragment or not parsed.hostname):
        raise ArchiveDownloadError("unreviewed archive redirect URL")
    host, path = parsed.hostname, parsed.path
    if host == "cdn.playwright.dev":
        return
    if (host == "playwright.download.prss.microsoft.com"
            and path.startswith("/dbazure/download/playwright/")):
        return
    # Official Chrome-for-Testing archive storage is only valid for Chromium.
    if (host == "storage.googleapis.com"
            and component == "chromium-headless-shell"
            and path.startswith("/chrome-for-testing-public/")):
        return
    raise ArchiveDownloadError("unreviewed archive redirect destination")


def download_archive(url: str, destination: Path, component: str) -> None:
    """GET one hop at a time; reject unknown redirects before contacting them."""
    deadline = time.monotonic() + MAX_SECONDS
    visited: set[str] = set()
    for _ in range(MAX_HOPS):
        validate_archive_url(url, component)
        if url in visited:
            raise ArchiveDownloadError("archive redirect loop")
        visited.add(url)
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("archive download exceeded total deadline")
        seconds = min(700, max(1, int(remaining)))
        command = [
            "curl", "-q", "--globoff", "--fail", "--silent", "--show-error",
            "--proto", "=https", "--retry", "3",
            "--connect-timeout", "25", "--max-time", str(seconds),
            "--max-filesize", str(MAX_BYTES),
            "--write-out", "%{http_code}\n%{redirect_url}",
            "--output", str(destination), url,
        ]
        response = subprocess.run(
            command, check=True, capture_output=True, text=True,
            timeout=remaining + 5,
        )
        code, sep, redirect = response.stdout.partition("\n")
        if not sep or re.fullmatch(r"[0-9]{3}", code) is None:
            raise ArchiveDownloadError("unrecognized HTTP response")
        redirect = redirect.strip()
        if code == "200" and not redirect:
            if not destination.is_file() or not 0 < destination.stat().st_size <= MAX_BYTES:
                raise ArchiveDownloadError("empty or oversized archive")
            return
        if code not in ("301", "302", "303", "307", "308") or not redirect:
            raise ArchiveDownloadError("unexpected archive HTTP status: " + code)
        validate_archive_url(redirect, component)
        url = redirect
    raise ArchiveDownloadError("too many archive redirects")
