#!/usr/bin/env python3
"""Record actual upstream version-pin deltas in the bounded Unreleased changelog section."""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

UNRELEASED_HEADING = "## [Unreleased]"
SECTION_HEADING = "### Automated upstream refreshes"
MARKER = "<!-- remote-dev-upstream-refreshes -->"

_COMPONENTS = (
    ("CODEX_RELEASE_TAG", "Codex CLI", lambda value: value.removeprefix("rust-v")),
    ("GH_VERSION", "GitHub CLI", lambda value: value),
    ("TTYD_VERSION", "ttyd", lambda value: value),
    ("MISE_VERSION", "mise", lambda value: value),
    ("PYTHON_VERSION", "Python", lambda value: value),
    ("NODE_VERSION", "Node.js", lambda value: value),
    ("NPM_VERSION", "npm", lambda value: value),
    ("UV_VERSION", "uv", lambda value: value),
    ("CONTEXT7_CLI_VERSION", "Context7 CLI (transient)", lambda value: value),
)
_ENV_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def parse_versions(path: Path) -> dict[str, str]:
    """Parse the repository's simple KEY=VALUE versions file without shell evaluation."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"{path}:{line_number}: expected a simple KEY=VALUE assignment")
        key, value = match.groups()
        if key in values:
            raise ValueError(f"{path}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def changed_components(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Return display strings only for tracked component versions that actually changed."""
    changes: list[str] = []
    for key, label, formatter in _COMPONENTS:
        if key not in before or key not in after:
            raise ValueError(f"required version pin {key} is missing")
        old = before[key]
        new = after[key]
        if old == new:
            continue
        changes.append(f"{label} {formatter(old)} → {formatter(new)}")
    return changes


def validate_date(value: str) -> None:
    """Require an exact real ISO calendar date."""
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("date must be a real ISO date in YYYY-MM-DD form") from exc
    if parsed.isoformat() != value:
        raise ValueError("date must use exact YYYY-MM-DD form")


def locate_managed_section(text: str) -> tuple[int, int]:
    """Return the Unreleased automated-section bounds only when the contract is unambiguous."""
    if text.count(UNRELEASED_HEADING) != 1:
        raise ValueError("CHANGELOG.md must contain exactly one Unreleased heading")
    unreleased_start = text.index(UNRELEASED_HEADING)
    next_release = text.find("\n## ", unreleased_start + len(UNRELEASED_HEADING))
    unreleased_end = len(text) if next_release == -1 else next_release
    unreleased = text[unreleased_start:unreleased_end]
    if unreleased.count(SECTION_HEADING) != 1:
        raise ValueError("Unreleased must contain exactly one Automated upstream refreshes section")
    if unreleased.count(MARKER) != 1:
        raise ValueError("Automated upstream refreshes must contain exactly one ownership marker")

    section_offset = unreleased.index(SECTION_HEADING)
    marker_offset = unreleased.index(MARKER)
    if marker_offset < section_offset:
        raise ValueError("upstream refresh ownership marker must follow its section heading")

    section_start = unreleased_start + section_offset
    next_heading = text.find("\n### ", section_start + len(SECTION_HEADING))
    section_end = unreleased_end if next_heading == -1 or next_heading >= unreleased_end else next_heading
    marker_index = unreleased_start + marker_offset
    return marker_index, section_end


def update_changelog(text: str, date: str, changes: list[str]) -> str:
    """Insert one newest-first automation entry while preserving all human-written text."""
    validate_date(date)
    marker_index, section_end = locate_managed_section(text)
    if not changes:
        return text
    entry = f"- {date} — {'; '.join(changes)}."
    managed_section = text[marker_index:section_end]
    if entry in managed_section.splitlines():
        return text
    marker_end = marker_index + len(MARKER)
    prefix = text[:marker_end]
    suffix = text[marker_end:].lstrip("\r\n")
    return f"{prefix}\n\n{entry}\n\n{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    before = parse_versions(args.before)
    after = parse_versions(args.after)
    changes = changed_components(before, after)
    original = args.changelog.read_text(encoding="utf-8")
    updated = update_changelog(original, args.date, changes)
    if updated != original:
        args.changelog.write_text(updated, encoding="utf-8")
    if changes:
        print("Automated changelog entry: " + "; ".join(changes))
    else:
        print("No tracked upstream version changes; changelog unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
