#!/usr/bin/env python3
"""Exercise the host-side Remote Dev data-layout preflight."""

from __future__ import annotations

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
    "state/codex/runtime",
    "state/codex/gh",
    "state/codex/git",
    "state/codex/ssh",
)
ANTIGRAVITY_DIRECTORY_SUFFIXES = (
    "workspaces/antigravity",
    "state/antigravity/bin",
    "state/antigravity/runtime",
    "state/antigravity/vendor",
    "state/antigravity/config",
    "state/antigravity/gh",
    "state/antigravity/git",
    "state/antigravity/ssh",
)


def run_preflight(
    root: Path, *, include_antigravity: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run the preflight against one temporary host layout."""
    command = [sys.executable, str(PREFLIGHT), "--root", str(root)]
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


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion for a failed regression expectation."""
    if not condition:
        raise AssertionError(message)


def validate_layouts(root: Path) -> None:
    """Require only persistent role data paths, never web-password files."""
    missing = run_preflight(root)
    require(missing.returncode == 1, "missing root must fail")
    require("required directory is missing" in missing.stderr, missing.stderr)

    create_directories(root, CODEX_DIRECTORY_SUFFIXES)
    codex_only = run_preflight(root)
    require(codex_only.returncode == 0, codex_only.stderr)
    require("; Codex)" in codex_only.stdout, codex_only.stdout)
    require(not (root / "secrets").exists(), "preflight unexpectedly requires secrets")

    missing_antigravity = run_preflight(root, include_antigravity=True)
    require(missing_antigravity.returncode == 1, "enabled Antigravity layout must exist")
    require("workspaces/antigravity" in missing_antigravity.stderr, missing_antigravity.stderr)

    antigravity_config_suffix = "state/antigravity/config"
    create_directories(
        root,
        tuple(
            suffix
            for suffix in ANTIGRAVITY_DIRECTORY_SUFFIXES
            if suffix != antigravity_config_suffix
        ),
    )
    missing_config = run_preflight(root, include_antigravity=True)
    require(missing_config.returncode == 1, "missing Antigravity config state must fail")
    require(
        f"required directory is missing: {root / antigravity_config_suffix}"
        in missing_config.stderr,
        missing_config.stderr,
    )
    (root / antigravity_config_suffix).mkdir()
    complete = run_preflight(root, include_antigravity=True)
    require(complete.returncode == 0, complete.stderr)
    require("; Codex + Antigravity)" in complete.stdout, complete.stdout)
    require(not (root / "secrets").exists(), "complete layout unexpectedly requires secrets")


def validate_symlinks(root: Path, temporary_directory: str) -> None:
    """Reject symlinks anywhere in the persistent role-data ancestry."""
    codex_runtime = root / "state/codex/runtime"
    codex_runtime.rmdir()
    codex_runtime.symlink_to(root / "state/codex/agent", target_is_directory=True)
    runtime_symlink = run_preflight(root, include_antigravity=True)
    require(runtime_symlink.returncode == 1, "symlinked Codex runtime directory must fail")
    require("must not be a symlink" in runtime_symlink.stderr, runtime_symlink.stderr)
    codex_runtime.unlink()
    codex_runtime.mkdir()

    antigravity_vendor = root / "state/antigravity/vendor"
    antigravity_vendor.rmdir()
    antigravity_vendor.symlink_to(root / "state/antigravity/runtime", target_is_directory=True)
    final_symlink = run_preflight(root, include_antigravity=True)
    require(final_symlink.returncode == 1, "symlinked Antigravity directory must fail")
    require("must not be a symlink" in final_symlink.stderr, final_symlink.stderr)
    antigravity_vendor.unlink()
    antigravity_vendor.mkdir()

    antigravity_config = root / "state/antigravity/config"
    antigravity_config.rmdir()
    antigravity_config.symlink_to(root / "state/antigravity/runtime", target_is_directory=True)
    config_symlink = run_preflight(root, include_antigravity=True)
    require(config_symlink.returncode == 1, "symlinked Antigravity config directory must fail")
    require("must not be a symlink" in config_symlink.stderr, config_symlink.stderr)
    antigravity_config.unlink()
    antigravity_config.mkdir()

    outside_state = Path(temporary_directory) / "outside-state"
    for child in ("agent", "runtime", "gh", "git", "ssh"):
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
    """Validate optional roles and persistent-path symlink ancestry."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory) / "remote-dev"
        create_directories(root, CODEX_DIRECTORY_SUFFIXES + ANTIGRAVITY_DIRECTORY_SUFFIXES)
        shutil.rmtree(root)
        validate_layouts(root)
        validate_symlinks(root, temporary_directory)

    print("Host data-layout preflight regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
