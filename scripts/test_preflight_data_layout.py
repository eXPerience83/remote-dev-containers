#!/usr/bin/env python3
"""Exercise the host-side Remote Dev data-layout preflight."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = ROOT / "scripts/preflight-data-layout.py"
DIRECTORY_SUFFIXES = (
    "workspaces/codex",
    "state/codex/agent",
    "state/codex/gh",
    "state/codex/git",
    "state/codex/ssh",
    "secrets/codex",
)
PASSWORD_SUFFIX = "secrets/codex/web_password.txt"


def run_preflight(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the preflight against one temporary host layout."""
    return subprocess.run(
        [sys.executable, str(PREFLIGHT), "--root", str(root)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def create_directories(root: Path) -> None:
    """Create every canonical directory without creating the password file."""
    root.mkdir(parents=True)
    for suffix in DIRECTORY_SUFFIXES:
        (root / suffix).mkdir(parents=True, exist_ok=True)


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion for a failed regression expectation."""
    if not condition:
        raise AssertionError(message)


def main() -> int:
    """Validate missing paths, password safety and the successful layout."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / "remote-dev"

        missing = run_preflight(root)
        require(missing.returncode == 1, "missing root must fail")
        require("required directory is missing" in missing.stderr, missing.stderr)

        create_directories(root)
        missing_password = run_preflight(root)
        require(missing_password.returncode == 1, "missing password must fail")
        require("password file is missing" in missing_password.stderr, missing_password.stderr)

        password_file = root / PASSWORD_SUFFIX
        password_file.write_text("test-only-password\n", encoding="utf-8")
        if os.name == "posix":
            password_file.chmod(0o644)
            broad = run_preflight(root)
            require(broad.returncode == 1, "broad password mode must fail")
            require("permissions are too broad" in broad.stderr, broad.stderr)
            password_file.chmod(0o600)

        valid = run_preflight(root)
        require(valid.returncode == 0, valid.stderr)
        require("data-layout preflight: OK" in valid.stdout, valid.stdout)

        marker = root / "state/codex/git"
        marker.rmdir()
        marker.symlink_to(root / "state/codex/gh", target_is_directory=True)
        symlinked = run_preflight(root)
        require(symlinked.returncode == 1, "symlinked state directory must fail")
        require("must not be a symlink" in symlinked.stderr, symlinked.stderr)

    print("Host data-layout preflight regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
