#!/usr/bin/env python3
"""Open Antigravity's conversation picker after its interactive prompt is ready."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence

_PANE_PATTERN = re.compile(r"^%[0-9]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PROMPT_PATTERN = re.compile(r"(?m)^\s*>\s*Describe\b")
_POLL_SECONDS = 0.1


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _capture_pane(pane: str) -> str | None:
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-J", "-t", pane],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _screen_digest(screen: str) -> str:
    return hashlib.sha256(screen.encode("utf-8")).hexdigest()


def snapshot(pane: str) -> str | None:
    screen = _capture_pane(pane)
    if screen is None:
        return None
    return _screen_digest(screen)


def _send_resume(pane: str) -> bool:
    commands = (
        ["tmux", "send-keys", "-t", pane, "-l", "/resume"],
        ["tmux", "send-keys", "-t", pane, "Enter"],
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
    return True


def watch(pane: str, pid: int, baseline_sha256: str) -> int:
    while _process_alive(pid):
        screen = _capture_pane(pane)
        if screen is not None:
            screen_changed = _screen_digest(screen) != baseline_sha256
            if screen_changed and _PROMPT_PATTERN.search(screen):
                return 0 if _send_resume(pane) else 1
        time.sleep(_POLL_SECONDS)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Antigravity's interactive conversation picker in tmux."
    )
    parser.add_argument("command", choices=("snapshot", "watch"))
    parser.add_argument("--pane", required=True)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--baseline-sha256")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not _PANE_PATTERN.fullmatch(args.pane):
        print("ERROR: --pane must be a tmux pane ID such as %1", file=sys.stderr)
        return 2

    if args.command == "snapshot":
        if args.pid is not None or args.baseline_sha256 is not None:
            print("ERROR: snapshot accepts only --pane", file=sys.stderr)
            return 2
        digest = snapshot(args.pane)
        if digest is None:
            print("ERROR: unable to capture the tmux pane", file=sys.stderr)
            return 1
        print(digest)
        return 0

    if args.pid is None or args.pid <= 0:
        print("ERROR: watch requires a positive --pid", file=sys.stderr)
        return 2
    if not args.baseline_sha256 or not _SHA256_PATTERN.fullmatch(
        args.baseline_sha256
    ):
        print("ERROR: watch requires a lowercase SHA-256 baseline", file=sys.stderr)
        return 2
    return watch(args.pane, args.pid, args.baseline_sha256)


if __name__ == "__main__":
    raise SystemExit(main())
