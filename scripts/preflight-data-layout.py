#!/usr/bin/env python3
"""Fail fast unless a canonical Remote Dev host data layout already exists."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.data_layout import canonical_path, validate_layout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the host-side canonical data-root preflight arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Verify that every enabled Remote Dev bind source exists before "
            "Docker Compose or TrueNAS is allowed to deploy it."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Host path corresponding to REMOTE_DEV_DATA_ROOT",
    )
    parser.add_argument(
        "--include-antigravity",
        action="store_true",
        help="Also require the optional isolated Antigravity service layout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the preflight and report only persistent path metadata."""
    args = parse_args(argv)
    root = canonical_path(args.root)
    errors = validate_layout(root, include_antigravity=args.include_antigravity)
    if errors:
        print("Remote Dev data-layout preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        print(
            "Run scripts/init-data-layout.py against the intended existing root, "
            "then retry this preflight before deploying.",
            file=sys.stderr,
        )
        return 1

    roles = "Codex + Antigravity" if args.include_antigravity else "Codex"
    print(f"Remote Dev data-layout preflight: OK ({root}; {roles})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
