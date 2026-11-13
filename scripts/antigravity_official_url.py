#!/usr/bin/env python3
"""Validate the fixed, reviewed HTTPS origin for Antigravity metadata.

Keep this predicate identical to the previous validators' shared contract.
Changing accepted URL bytes requires a separate security review.
"""

from __future__ import annotations

import urllib.parse

OFFICIAL_HOST = "antigravity.google"


def safe_official_url(value: object) -> bool:
    """Return whether a URL remains on the reviewed official HTTPS origin."""
    if not isinstance(value, str) or not value or "\\" in value:
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
