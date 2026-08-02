#!/usr/bin/env python3
"""Regression tests for the fail-closed Antigravity CLI inspection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/inspect-antigravity-cli.py"
FIXTURE = ROOT / "scripts/fixtures/antigravity-install.sh"
UNTRUSTED_MARKER = "UNTRUSTED_VENDOR_OUTPUT_SHOULD_NOT_APPEAR"


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion when a regression expectation fails."""
    if not condition:
        raise AssertionError(message)


def run_inspection(
    report_path: Path,
    fixture: Path,
    *,
    expected_installer_sha256: str | None = None,
    expected_binary_sha256: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the inspector against one local non-network fixture."""
    command = [
        sys.executable,
        str(SCRIPT),
        "--output",
        str(report_path),
        "--installer-fixture",
        str(fixture),
    ]
    if expected_installer_sha256 is not None:
        command.extend(["--expected-installer-sha256", expected_installer_sha256])
    if expected_binary_sha256 is not None:
        command.extend(["--expected-binary-sha256", expected_binary_sha256])
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError("fixture inspection exceeded 120 seconds") from error


def assert_no_raw_output_fields(value: Any) -> None:
    """Reject legacy or accidental raw-output fields recursively."""
    if isinstance(value, dict):
        forbidden = {
            "stdout",
            "stderr",
            "stdout_lines",
            "stderr_lines",
            "raw_content",
            "raw_binary",
            "installer_bytes",
            "binary_bytes",
        }
        require(not (set(value) & forbidden), f"raw-output key found: {set(value) & forbidden}")
        for child in value.values():
            assert_no_raw_output_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_raw_output_fields(child)


def write_profile_mutating_fixture(path: Path) -> None:
    """Create an installer whose help path mutates a tracked shell profile."""
    path.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ \"${1:-}\" == \"--help\" ]]; then
  printf 'mutated\\n' >> \"$HOME/.bashrc\"
  printf '%s\\n' 'Usage: install.sh [options]' '--dir <path>'
  exit 0
fi
[[ \"${1:-}\" == \"--dir\" && -n \"${2:-}\" ]] || exit 2
mkdir -p \"$2\"
cp /bin/true \"$2/agy\"
""",
        encoding="utf-8",
    )
    path.chmod(0o700)


def main() -> int:
    """Exercise success and every pre-execution rejection boundary."""
    with tempfile.TemporaryDirectory() as temporary:
        temporary_path = Path(temporary)
        report_path = temporary_path / "report.json"
        completed = run_inspection(report_path, FIXTURE)
        require(completed.returncode == 0, completed.stderr)
        report = json.loads(report_path.read_text(encoding="utf-8"))

        require(report["schema_version"] == 2, "unexpected report schema")
        require(report["blocking_findings"] == [], "fixture inspection must pass")
        require(report["expected_binary_present"] is True, "fixture binary not detected")
        require(report["home_unchanged_after_help"] is True, "help mutated the home")
        require(
            report["profiles"]["unchanged_after_help"] is True,
            "fixture help unexpectedly changed a shell profile",
        )
        require(
            report["profiles"]["unchanged_after_first"] is True,
            "fixture unexpectedly changed a shell profile",
        )
        require(
            report["profiles"]["unchanged_after_second"] is True,
            "fixture unexpectedly changed a shell profile on repeat install",
        )
        require(
            report["binary_stable_across_second_install"] is True,
            "repeated fixture install changed executable hash",
        )
        require(
            report["binary_after_second"]["version"]["reported_version"]
            == "0.0.0-fixture",
            "version metadata was not normalized",
        )
        require(
            report["binary_after_second"]["help"]["exit_code"] == 0,
            "binary help result was not validated",
        )
        require(
            report["environment_controls"]["auto_update_disabled"] is True,
            "auto-update must be disabled during inspection",
        )
        serialized = json.dumps(report, sort_keys=True)
        require(UNTRUSTED_MARKER not in serialized, "vendor output leaked into evidence")
        require(UNTRUSTED_MARKER not in completed.stdout, "vendor output leaked to stdout")
        require(UNTRUSTED_MARKER not in completed.stderr, "vendor output leaked to stderr")
        assert_no_raw_output_fields(report)

        installer_mismatch_report = temporary_path / "installer-mismatch.json"
        installer_mismatch = run_inspection(
            installer_mismatch_report,
            FIXTURE,
            expected_installer_sha256="0" * 64,
        )
        require(installer_mismatch.returncode == 1, "unapproved installer hash must fail")
        require(
            not installer_mismatch_report.exists(),
            "installer hash mismatch must produce no evidence file",
        )
        require(
            UNTRUSTED_MARKER not in installer_mismatch.stdout + installer_mismatch.stderr,
            "fixture ran before installer hash rejection",
        )

        binary_mismatch_report = temporary_path / "binary-mismatch.json"
        binary_mismatch = run_inspection(
            binary_mismatch_report,
            FIXTURE,
            expected_binary_sha256="0" * 64,
        )
        require(binary_mismatch.returncode == 1, "unapproved binary hash must fail")
        require(
            not binary_mismatch_report.exists(),
            "binary hash mismatch must produce no evidence file",
        )
        require(
            "installed binary SHA-256 differs" in binary_mismatch.stderr,
            "binary digest rejection was not reported",
        )

        mutating_fixture = temporary_path / "mutating-install.sh"
        write_profile_mutating_fixture(mutating_fixture)
        mutation_report = temporary_path / "mutation.json"
        mutation = run_inspection(mutation_report, mutating_fixture)
        require(mutation.returncode == 1, "help profile mutation must fail")
        require(
            not mutation_report.exists(),
            "help mutation must abort before evidence generation",
        )
        require(
            "help changed the isolated home" in mutation.stderr,
            "help-side-effect rejection was not reported",
        )

    print("Fail-closed Antigravity installer inspection regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
