#!/usr/bin/env python3
"""Validate the fixed official HTTPS origin for Antigravity metadata.

Reject malformed raw URL bytes before the standard URL parser normalizes them.
The original shared host/scheme/port/credentials/fragment policy is unchanged.
"""

from __future__ import annotations

import urllib.parse

OFFICIAL_HOST = "antigravity.google"


def has_unsafe_raw_url_characters(value: str) -> bool:
    """Reject unescaped ASCII controls and spaces before URL normalization."""
    return any(ord(char) <= 0x20 or ord(char) == 0x7f for char in value)


def safe_official_url(value: object) -> bool:
    """Return whether a URL remains on the reviewed official HTTPS origin."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    # urlsplit strips leading C0/space and embedded TAB, CR and LF. Reject
    # unescaped ASCII controls/spaces *before* parsing to avoid validating a
    # different origin string than the raw metadata supplied to this boundary.
    if has_unsafe_raw_url_characters(value):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == OFFICIAL_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
    )
