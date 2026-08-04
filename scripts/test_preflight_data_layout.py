#!/usr/bin/env python3
"""Exercise the host-side Remote Dev data-layout preflight."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFLIGHT = ROOT / "scripts/preflight-data-layout.py"
CODEX_DIRECTORY_SUFFIXES = (
    "workspaces/codex",
    "state/codex/agent",
    "state/codex/gh",
    "state/codex/git",
    "state/codex/ssh",
)
ANTIGRAVITY_DIRECTORY_SUFFIXES = (
    "workspaces/antigravity",
    "state/antigravity/bin",
    "state/antigravity/runtime",
    "state/antigravity/vendor",
    "state/antigravity/gh",
    "state/antigravity/git",
    "state/antigravity/ssh",
)
CODEX_SECRET_DIRECTORY_SUFFIX = "secrets/codex"
ANTIGRAVITY_SECRET_DIRECTORY_SUFFIX = "secrets/antigravity"
CODEX_PASSWORD_SUFFIX = "secrets/codex/web_password.txt"
ANTIGRAVITY_PASSWORD_SUFFIX = "secrets/antigravity/web_password.txt"


def run_preflight(
    root: Path,
    *,
    include_antigravity: bool = False,
    password_source: str = "environment",
) -> subprocess.CompletedProcess[str]:
    """Run the preflight against one temporary host layout."""
    command = [
        sys.executable,
        str(PREFLIGHT),
        "--root",
        str(root),
        "--password-source",
        password_source,
    ]
    if include_antigravity:
        command.append("--include-antigravity")
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def create_directories(root: Path, suffixes: tuple[str, ...]) -> None:
    """Create one role's canonical directories."""
    root.mkdir(parents=True, exist_ok=True)
    for suffix in suffixes:
        (root / suffix).mkdir(parents=True, exist_ok=True)


def write_password(root: Path, suffix: str, value: str) -> Path:
    """Create one synthetic restrictive terminal-password file."""
    path = root / suffix
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{value}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion for a failed regression expectation."""
    if not condition:
        raise AssertionError(message)


def validate_environment_mode(root: Path) -> None:
    """Environment-backed passwords must require only persistent data paths."""
    missing = run_preflight(root)
    require(missing.returncode == 1, "missing root must fail")
    require("required directory is missing" in missing.stderr, missing.stderr)

    create_directories(root, CODEX_DIRECTORY_SUFFIXES)
    codex_only = run_preflight(root)
    require(codex_only.returncode == 0, codex_only.stderr)
    require("Codex; passwords=environment" in codex_only.stdout, codex_only.stdout)
    require(not (root / "secrets").exists(), "environment mode created secrets")

    missing_antigravity = run_preflight(root, include_antigravity=True)
    require(missing_antigravity.returncode == 1, "enabled Antigravity layout must exist")
    require("workspaces/antigravity" in missing_antigravity.stderr, missing_antigravity.stderr)

    create_directories(root, ANTIGRAVITY_DIRECTORY_SUFFIXES)
    complete = run_preflight(root, include_antigravity=True)
    require(complete.returncode == 0, complete.stderr)
    require(
        "Codex + Antigravity; passwords=environment" in complete.stdout,
        complete.stdout,
    )


def validate_file_mode(root: Path) -> None:
    """File-backed passwords retain strict path, content and mode checks."""
    missing_secret_dir = run_preflight(root, password_source="file")
    require(missing_secret_dir.returncode == 1, "missing Codex secret directory must fail")
    require(CODEX_SECRET_DIRECTORY_SUFFIX in missing_secret_dir.stderr, missing_secret_dir.stderr)

    (root / CODEX_SECRET_DIRECTORY_SUFFIX).mkdir(parents=True)
    missing_password = run_preflight(root, password_source="file")
    require(missing_password.returncode == 1, "missing Codex password must fail")
    require("password file is missing" in missing_password.stderr, missing_password.stderr)

    codex_password = root / CODEX_PASSWORD_SUFFIX
    codex_password.write_bytes(b"\n\n")
    codex_password.chmod(0o600)
    newline_only = run_preflight(root, password_source="file")
    require(newline_only.returncode == 1, "newline-only password must fail")
    require("empty after trailing newline removal" in newline_only.stderr, newline_only.stderr)

    codex_password.write_bytes(b"first-line\nsecond-line\n")
    multiline = run_preflight(root, password_source="file")
    require(multiline.returncode == 1, "multiline password must fail")
    require("must be a single LF-terminated line" in multiline.stderr, multiline.stderr)

    codex_password = write_password(root, CODEX_PASSWORD_SUFFIX, "test-codex-password")
    if os.name == "posix":
        codex_password.chmod(0o644)
        broad = run_preflight(root, password_source="file")
        require(broad.returncode == 1, "broad password mode must fail")
        require("permissions are too broad" in broad.stderr, broad.stderr)
        codex_password.chmod(0o600)

    codex_only = run_preflight(root, password_source="file")
    require(codex_only.returncode == 0, codex_only.stderr)
    require("Codex; passwords=file" in codex_only.stdout, codex_only.stdout)

    missing_antigravity_secret = run_preflight(
        root, include_antigravity=True, password_source="file"
    )
    require(
        missing_antigravity_secret.returncode == 1,
        "missing Antigravity secret directory must fail",
    )
    require(
        ANTIGRAVITY_SECRET_DIRECTORY_SUFFIX in missing_antigravity_secret.stderr,
        missing_antigravity_secret.stderr,
    )

    (root / ANTIGRAVITY_SECRET_DIRECTORY_SUFFIX).mkdir(parents=True)
    missing_antigravity_password = run_preflight(
        root, include_antigravity=True, password_source="file"
    )
    require(missing_antigravity_password.returncode == 1, "missing Antigravity password must fail")
    require(
        ANTIGRAVITY_PASSWORD_SUFFIX in missing_antigravity_password.stderr,
        missing_antigravity_password.stderr,
    )
    write_password(root, ANTIGRAVITY_PASSWORD_SUFFIX, "test-antigravity-password")

    complete = run_preflight(root, include_antigravity=True, password_source="file")
    require(complete.returncode == 0, complete.stderr)
    require("Codex + Antigravity; passwords=file" in complete.stdout, complete.stdout)


def validate_symlinks(root: Path, temporary_directory: str) -> None:
    """Both final and intermediate persistent path symlinks must fail."""
    antigravity_vendor = root / "state/antigravity/vendor"
    antigravity_vendor.rmdir()
    antigravity_vendor.symlink_to(root / "state/antigravity/runtime", target_is_directory=True)
    final_symlink = run_preflight(root, include_antigravity=True)
    require(final_symlink.returncode == 1, "symlinked Antigravity directory must fail")
    require("must not be a symlink" in final_symlink.stderr, final_symlink.stderr)
    antigravity_vendor.unlink()
    antigravity_vendor.mkdir()

    outside_state = Path(temporary_directory) / "outside-state"
    for child in ("agent", "gh", "git", "ssh"):
        (outside_state / child).mkdir(parents=True, exist_ok=True)
    state_codex = root / "state/codex"
    shutil.rmtree(state_codex)
    state_codex.symlink_to(outside_state, target_is_directory=True)
    intermediate_symlink = run_preflight(root, include_antigravity=True)
    require(intermediate_symlink.returncode == 1, "symlinked intermediate directory must fail")
    require(
        f"must not be a symlink: {state_codex}" in intermediate_symlink.stderr,
        intermediate_symlink.stderr,
    )


def main() -> int:
    """Validate optional roles, both password modes and symlink ancestry."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / "remote-dev"
        validate_environment_mode(root)
        validate_file_mode(root)
        validate_symlinks(root, temporary_directory)

    print("Host data-layout preflight regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
