#!/usr/bin/env python3
"""Select a PyPI CLI only after *all* its published files clear mise's 24h cutoff.

GitHub Releases is the upstream version signal, but mise/uv resolves the native
Python graph from PyPI. An early GitHub release can therefore be younger than
mise's minimum_release_age for its PyPI distributions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MINIMUM_RELEASE_AGE = timedelta(hours=24)
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ALLOWED_PACKAGES = {"ruff", "pytest", "pre-commit"}


def version_parts(value: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(value):
        raise ValueError(f"unsupported stable PyPI version: {value!r}")
    return tuple(map(int, value.split(".")))


def normalize_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def select_version(
    *, package: str, current: str, candidate: str, metadata: dict[str, Any],
    now: datetime,
) -> tuple[str, str]:
    if package not in ALLOWED_PACKAGES:
        raise ValueError(f"unreviewed PyPI package: {package}")
    if now.tzinfo is None:
        raise ValueError("current time must be timezone aware")
    old, new = version_parts(current), version_parts(candidate)
    if new <= old:
        return current, "no newer upstream version"

    info = metadata.get("info")
    if not isinstance(info, dict) or normalize_name(str(info.get("name", ""))) != package:
        raise ValueError(f"{package}: PyPI metadata has a mismatched project identity")
    if info.get("version") != candidate:
        raise ValueError(f"{package}: PyPI metadata version differs from GitHub candidate")

    files = metadata.get("urls")
    if not isinstance(files, list) or not files:
        raise ValueError(f"{package}: missing PyPI distribution files")
    upload_times: list[datetime] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError(f"{package}: invalid PyPI distribution")
        if entry.get("yanked") is True:
            continue
        if not isinstance(entry.get("filename"), str) or not entry["filename"]:
            raise ValueError(f"{package}: missing distribution filename")
        raw = entry.get("upload_time_iso_8601")
        if not isinstance(raw, str) or not raw:
            raise ValueError(f"{package}: missing PyPI upload timestamp")
        try:
            uploaded = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{package}: invalid PyPI upload timestamp") from exc
        if uploaded.tzinfo is None:
            raise ValueError(f"{package}: timezone-free PyPI timestamp")
        upload_times.append(uploaded.astimezone(timezone.utc))
    if not upload_times:
        raise ValueError(f"{package}: no active PyPI distributions")

    # Use the LAST publication, rather than the first: uv's cutoff must not
    # silently exclude a late wheel when generating a cross-platform graph.
    newest_file = max(upload_times)
    cutoff = now.astimezone(timezone.utc) - MINIMUM_RELEASE_AGE
    if newest_file > cutoff:
        return current, (
            f"PyPI {package} {candidate} is newer than mise's 24h safety cutoff "
            f"(last file {newest_file.isoformat()}); retain {current}"
        )
    return candidate, f"PyPI {package} {candidate} is beyond mise's 24h safety cutoff"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, choices=sorted(ALLOWED_PACKAGES))
    parser.add_argument("--current", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.metadata.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
        if not isinstance(metadata, dict):
            raise ValueError("PyPI release response must be a JSON object")
        selected, reason = select_version(
            package=args.package, current=args.current,
            candidate=args.candidate, metadata=metadata,
            now=datetime.now(timezone.utc),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot safely select PyPI {args.package}: {exc}", file=sys.stderr)
        return 1
    print(reason, file=sys.stderr)
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
