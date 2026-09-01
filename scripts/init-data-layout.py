#!/usr/bin/env python3
"""Initialize the canonical Remote Dev host data layout below an existing root."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lib.data_layout import canonical_path, initialize_layout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse host-side data-layout bootstrap arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Create missing canonical Remote Dev bind-source directories below "
            "an existing host root, then validate the completed layout."
        )
    )
    parser.add_argument(
        "--root",
        required=True,
        type=Path,
        help="Existing host path corresponding to REMOTE_DEV_DATA_ROOT",
    )
    parser.add_argument(
        "--include-antigravity",
        action="store_true",
        help="Also initialize the optional isolated Antigravity service layout",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Initialize only missing directories and never create the configured root."""
    args = parse_args(argv)
    root = canonical_path(args.root)
    try:
        created = initialize_layout(root, include_antigravity=args.include_antigravity)
    except ValueError as exc:
        print("Remote Dev data-layout bootstrap failed:", file=sys.stderr)
        print(f"- {exc}", file=sys.stderr)
        print(
            "The configured root must already be the intended administrator-created "
            "dataset/directory. No root, migration or secret files were created.",
            file=sys.stderr,
        )
        return 1

    roles = "Codex + Antigravity" if args.include_antigravity else "Codex"
    if created:
        print(f"Remote Dev data-layout bootstrap: created {len(created)} directorie(s)")
    else:
        print("Remote Dev data-layout bootstrap: no changes required")
    print(f"Remote Dev data-layout bootstrap: OK ({root}; {roles})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
