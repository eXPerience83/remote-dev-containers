#!/usr/bin/env python3
"""Strict bounded HTTPS downloads for Antigravity review tooling."""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

UrlPolicy = Callable[[str], bool]


class DownloadError(RuntimeError):
    """Raised when a download violates its reviewed network contract."""


class PolicyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject a redirect before urllib can request an unreviewed target."""

    def __init__(self, policy: UrlPolicy):
        super().__init__()
        self._policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        if not self._policy(newurl):
            raise DownloadError("download redirect left the reviewed HTTPS policy")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_bytes(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    policy: UrlPolicy,
    user_agent: str,
    timeout: int = 60,
) -> tuple[bytes, str | None, str]:
    """Download bounded bytes while validating the initial, redirect and final URL."""
    if max_bytes <= 0:
        raise DownloadError("download byte limit must be positive")
    if not policy(url):
        raise DownloadError("download URL violates the reviewed HTTPS policy")

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        PolicyRedirectHandler(policy),
    )
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with opener.open(request, timeout=timeout) as response:
            final_url = response.geturl()
            if not policy(final_url):
                raise DownloadError("download final URL violates the reviewed HTTPS policy")
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise DownloadError("download exceeds the reviewed size boundary")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return data, response.headers.get_content_type(), final_url
    except DownloadError:
        raise
    except (OSError, urllib.error.URLError) as error:
        raise DownloadError(f"bounded HTTPS download failed: {error}") from error
