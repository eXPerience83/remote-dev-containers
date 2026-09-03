#!/usr/bin/env python3
"""Format one human-readable edge build identity from trusted publication inputs."""

from __future__ import annotations

import argparse
import datetime as dt
import re

_SOURCE_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")


def format_edge_identity(build_date: str, source_revision: str) -> str:
    """Return edge-YYYY.MM.DD-<7-char-sha> after strict input validation."""
    try:
        parsed_date = dt.date.fromisoformat(build_date)
    except ValueError as exc:
        raise ValueError("build date must be a real ISO date in YYYY-MM-DD form") from exc
    if parsed_date.isoformat() != build_date:
        raise ValueError("build date must use exact YYYY-MM-DD form")
    if not _SOURCE_REVISION_RE.fullmatch(source_revision):
        raise ValueError("source revision must be a lowercase 40-character Git SHA")
    return f"edge-{build_date.replace('-', '.')}-{source_revision[:7]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="UTC publication date as YYYY-MM-DD")
    parser.add_argument("--source-revision", required=True, help="full lowercase 40-char Git SHA")
    args = parser.parse_args()
    try:
        print(format_edge_identity(args.date, args.source_revision))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
