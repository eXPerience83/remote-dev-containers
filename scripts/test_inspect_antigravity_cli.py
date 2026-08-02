#!/usr/bin/env python3
"""Regression tests for the bounded Antigravity CLI installer inspection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/inspect-antigravity-cli.py"
FIXTURE = ROOT / "scripts/fixtures/antigravity-install.sh"


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion when a regression expectation fails."""
    if not condition:
        raise AssertionError(message)


def main() -> int:
    """Run the inspection against a local non-network fixture."""
    with tempfile.TemporaryDirectory() as temporary:
        report_path = Path(temporary) / "report.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--output",
                str(report_path),
                "--installer-fixture",
                str(FIXTURE),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        require(completed.returncode == 0, completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))

    require(report["schema_version"] == 1, "unexpected report schema")
    require(report["blocking_findings"] == [], "fixture inspection must pass")
    require(report["expected_binary_present"] is True, "fixture binary not detected")
    require(
        report["profiles"]["unchanged_after_first"] is True,
        "fixture unexpectedly changed a shell profile",
    )
    require(
        report["profiles"]["unchanged_after_second"] is True,
        "fixture unexpectedly changed a shell profile on update",
    )
    require(
        report["binary_stable_across_second_install"] is True,
        "idempotent fixture changed executable hash",
    )
    require(
        report["binary_after_second"]["version"]["stdout_lines"]
        == ["Antigravity CLI 0.0.0-fixture"],
        "version metadata was not captured safely",
    )
    require(
        report["filesystem"]["before"] == [],
        "inspection home must begin empty",
    )
    require(
        not any(entry["path"].endswith("install.sh") for entry in report["filesystem"]["after_second"]),
        "installer bytes must not be copied into the inspected home",
    )
    print("Bounded Antigravity installer inspection regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
