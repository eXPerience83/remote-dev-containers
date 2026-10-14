#!/usr/bin/env python3
"""Regression guard for the bounded, write-capable Python/upstream update step."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

STEP = "      - name: Check stable upstream releases and review metadata\n"
RUN = "        run: |\n"
GUARD = (
    "if ! grep -Eq '^python = "
    '\\["3[.]14[.][0-9]+", "3[.]15[.][0-9]+"\\]$'
    "' mise.toml; then"
)
REQUIRED_ONCE = (
    GUARD,
    'sed -i "s|^python = .*|python = [\\"${latest_python}\\", \\"${latest_python_315}\\"]|" mise.toml',
    'replace_env PYTHON_VERSION "$latest_python"',
    'replace_env PYTHON_315_VERSION "$latest_python_315"',
    'replace_mise_tool node "$latest_node"',
    'replace_mise_tool uv "$latest_uv"',
    'git commit -m "chore: update upstream versions and review evidence"',
    'git push --force-with-lease -u origin "$branch"',
    'gh pr create \\',
    'gh pr edit "$existing_pr" \\',
)


def shell_step(text: str) -> str:
    """Extract the intended updater shell step, never an unrelated workflow step."""
    if text.count(STEP) != 1:
        raise AssertionError("upstream workflow needs exactly one update step")
    suffix = text.split(STEP, 1)[1]
    if RUN not in suffix:
        raise AssertionError("upstream update step must contain a script block")
    body = suffix.split(RUN, 1)[1]
    lines = []
    for line in body.splitlines():
        if line and not line.startswith("          "):
            break
        lines.append(line[10:] if line.startswith("          ") else "")
    if len(lines) < 250:
        raise AssertionError("truncated updater shell block")
    return "\n".join(lines) + "\n"


def validate_step(body: str) -> None:
    """Require syntactically valid Bash and one coherent update/PR flow."""
    result = subprocess.run(
        ["bash", "-n"], input=body, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise AssertionError(f"updater Bash syntax invalid: {result.stderr.strip()}")
    for fragment in REQUIRED_ONCE:
        if body.count(fragment) != 1:
            raise AssertionError(f"updater must contain exactly one {fragment!r}")
    if body.index(GUARD) > body.index('replace_mise_tool node "$latest_node"'):
        raise AssertionError("dual-Python guard must precede other mise updates")
    if body.index('git commit -m "chore: update upstream versions and review evidence"') > body.index('gh pr create \\'):
        raise AssertionError("updater must commit changes before proposing a PR")


def expect_rejection(body: str) -> None:
    try:
        validate_step(body)
    except AssertionError:
        return
    raise AssertionError("unsafe/corrupted updater fixture was accepted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    body = shell_step((root / ".github/workflows/check-upstream.yml").read_text(encoding="utf-8"))
    validate_step(body)
    expect_rejection(body.replace(GUARD, GUARD.replace("' mise.toml; then", ""), 1))
    expect_rejection(body + '\ngit commit -m "chore: update upstream versions and review evidence"\n')
    expect_rejection(body.replace('replace_env PYTHON_315_VERSION "$latest_python_315"', "# removed 3.15 update", 1))
    print("Dual-Python upstream updater shell and single-flow regression: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
