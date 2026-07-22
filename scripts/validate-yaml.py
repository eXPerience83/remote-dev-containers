#!/usr/bin/env python3
from pathlib import Path
import sys
import yaml

failed = False
for path in sorted(Path("compose").glob("*.yml")):
    try:
        with path.open("r", encoding="utf-8") as handle:
            yaml.safe_load(handle)
        print(f"OK: {path}")
    except Exception as exc:
        failed = True
        print(f"ERROR: {path}: {exc}", file=sys.stderr)
raise SystemExit(1 if failed else 0)
