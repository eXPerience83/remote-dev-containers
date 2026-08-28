#!/usr/bin/env python3
"""Validate Webpack's emitted module roots against the fixed runtime allowlist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


EXPECTED = {
    "@xterm/addon-canvas", "@xterm/addon-fit", "@xterm/addon-image",
    "@xterm/addon-unicode11", "@xterm/addon-web-links", "@xterm/addon-webgl",
    "@xterm/xterm", "css-loader", "crc-32", "decko", "file-saver", "preact", "trzsz",
    "whatwg-fetch", "zmodem.js",
}


def visit(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from visit(child)
    elif isinstance(value, list):
        for child in value:
            yield from visit(child)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stats", type=Path)
    args = parser.parse_args()
    stats = json.loads(args.stats.read_text())
    roots: set[str] = set()
    pattern = re.compile(r"node_modules/((?:@[^/]+/)?[^/!]+)")
    for item in visit(stats):
        identifier = item.get("identifier")
        if not isinstance(identifier, str):
            continue
        resource = identifier.rsplit("!", 1)[-1]
        match = pattern.search(resource)
        if match:
            roots.add(match.group(1))
    if roots != EXPECTED:
        missing = sorted(EXPECTED - roots)
        extra = sorted(roots - EXPECTED)
        raise SystemExit(f"ERROR: emitted package roots differ; missing={missing}, extra={extra}")
    print(f"Remote Dev ttyd client bundle roots: OK ({len(roots)} packages)")


if __name__ == "__main__":
    main()
