#!/usr/bin/env python3
"""Exercise the canonical host-side Remote Dev data-layout bootstrap and preflight."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lib.data_layout import (  # noqa: E402
    ANTIGRAVITY_DIRECTORY_SPECS,
    CODEX_DIRECTORY_SPECS,
)

PREFLIGHT = SCRIPTS / "preflight-data-layout.py"
BOOTSTRAP = SCRIPTS / "init-data-layout.py"
TRUENAS = ROOT / "compose/truenas.yml"


def run_script(
    script: Path, root: Path, *, include_antigravity: bool = False
) -> subprocess.CompletedProcess[str]:
    """Run one host-side layout command against a temporary root."""
    command = [sys.executable, str(script), "--root", str(root)]
    if include_antigravity:
        command.append("--include-antigravity")
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion for a failed regression expectation."""
    if not condition:
        raise AssertionError(message)


def expected_suffixes(*, include_antigravity: bool) -> set[str]:
    specs = CODEX_DIRECTORY_SPECS
    if include_antigravity:
        specs += ANTIGRAVITY_DIRECTORY_SPECS
    return {spec.suffix for spec in specs}


def validate_bootstrap(root: Path) -> None:
    """Bootstrap both supported role selections safely and idempotently."""
    missing_root = run_script(BOOTSTRAP, root)
    require(missing_root.returncode == 1, "bootstrap must refuse a missing root")
    require("must already exist" in missing_root.stderr, missing_root.stderr)
    require(not root.exists(), "bootstrap unexpectedly created the configured root")

    root.mkdir()
    marker = root / "operator-marker.txt"
    marker.write_text("keep-me", encoding="utf-8")

    # A pre-existing path may be an ordinary directory or a deliberately created
    # TrueNAS child dataset mountpoint. Bootstrap must accept it as-is rather
    # than replacing it or normalizing its existing permissions/content.
    existing_workspace = root / "workspaces/codex"
    existing_workspace.mkdir(parents=True, mode=0o750)
    existing_workspace.chmod(0o750)
    dataset_marker = existing_workspace / "operator-dataset-marker.txt"
    dataset_marker.write_text("leave-existing-path-alone", encoding="utf-8")
    original_mode = existing_workspace.stat().st_mode & 0o777

    codex = run_script(BOOTSTRAP, root)
    require(codex.returncode == 0, codex.stderr)
    require(
        run_script(PREFLIGHT, root).returncode == 0,
        "Codex preflight must pass after bootstrap",
    )
    require(
        marker.read_text(encoding="utf-8") == "keep-me",
        "bootstrap modified existing root content",
    )
    require(
        dataset_marker.read_text(encoding="utf-8") == "leave-existing-path-alone",
        "bootstrap modified an existing persistent path",
    )
    require(
        (existing_workspace.stat().st_mode & 0o777) == original_mode,
        "bootstrap changed permissions on an existing persistent path",
    )
    require(
        not (root / "secrets").exists(),
        "bootstrap unexpectedly created a secrets tree",
    )

    second = run_script(BOOTSTRAP, root)
    require(second.returncode == 0, second.stderr)
    require("no changes required" in second.stdout, second.stdout)

    antigravity = run_script(BOOTSTRAP, root, include_antigravity=True)
    require(antigravity.returncode == 0, antigravity.stderr)
    complete = run_script(PREFLIGHT, root, include_antigravity=True)
    require(complete.returncode == 0, complete.stderr)
    require(
        not (root / "secrets").exists(),
        "complete layout unexpectedly created secrets",
    )

    existing_state = root / "state/codex/agent/existing-state.txt"
    existing_state.write_text("preserve", encoding="utf-8")
    rerun = run_script(BOOTSTRAP, root, include_antigravity=True)
    require(rerun.returncode == 0, rerun.stderr)
    require(
        existing_state.read_text(encoding="utf-8") == "preserve",
        "bootstrap changed existing state contents",
    )


def validate_symlinks(base: Path) -> None:
    """Reject root, root-ancestry and descendant symlinks without mutation."""
    real_root = base / "real-root"
    real_root.mkdir()
    linked_root = base / "linked-root"
    linked_root.symlink_to(real_root, target_is_directory=True)
    root_symlink = run_script(BOOTSTRAP, linked_root)
    require(root_symlink.returncode == 1, "symlink root must fail")
    require("must not be a symlink" in root_symlink.stderr, root_symlink.stderr)
    require(
        list(real_root.iterdir()) == [],
        "symlink-root target was unexpectedly modified",
    )

    real_parent = base / "real-parent"
    real_parent.mkdir()
    ancestry_root = real_parent / "remote-dev"
    ancestry_root.mkdir()
    linked_parent = base / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    ancestry_symlink = run_script(BOOTSTRAP, linked_parent / "remote-dev")
    require(
        ancestry_symlink.returncode == 1,
        "symlink in configured root ancestry must fail",
    )
    require("must not be a symlink" in ancestry_symlink.stderr, ancestry_symlink.stderr)
    require(
        list(ancestry_root.iterdir()) == [],
        "root-ancestry symlink target was unexpectedly modified",
    )
    ancestry_preflight = run_script(PREFLIGHT, linked_parent / "remote-dev")
    require(
        ancestry_preflight.returncode == 1,
        "preflight must also reject symlinked root ancestry",
    )
    require("must not be a symlink" in ancestry_preflight.stderr, ancestry_preflight.stderr)

    root = base / "intermediate-root"
    root.mkdir()
    outside = base / "outside"
    outside.mkdir()
    (root / "state").symlink_to(outside, target_is_directory=True)
    intermediate = run_script(BOOTSTRAP, root)
    require(intermediate.returncode == 1, "symlinked intermediate path must fail")
    require("must not be a symlink" in intermediate.stderr, intermediate.stderr)
    require(
        list(outside.iterdir()) == [],
        "symlinked external target was unexpectedly modified",
    )


def validate_compose_contract() -> None:
    """Keep the canonical Python contract exactly aligned with TrueNAS bind sources."""
    text = TRUENAS.read_text(encoding="utf-8")
    sources = {
        match.group(1)
        for match in re.finditer(
            r"^\s*source:\s*/mnt/Pool1/remote-dev/([^\s]+)\s*$",
            text,
            re.MULTILINE,
        )
    }
    expected = expected_suffixes(include_antigravity=True)
    require(
        sources == expected,
        "TrueNAS bind sources differ from canonical layout: "
        f"expected={sorted(expected)} actual={sorted(sources)}",
    )
    require("state/codex/runtime" in sources, "Codex runtime bind source disappeared")
    retired_password_file_var = "WEB_PASSWORD_" + "FILE"
    require(
        retired_password_file_var not in text,
        "TrueNAS YAML reintroduced the retired browser password-file variable",
    )
    require(
        "/secrets/" not in text,
        "TrueNAS YAML unexpectedly contains a web-password secrets bind",
    )


def validate_initial_modes(root: Path) -> None:
    """Apply intentional modes only to paths created by bootstrap."""
    root.mkdir()
    result = run_script(BOOTSTRAP, root, include_antigravity=True)
    require(result.returncode == 0, result.stderr)

    for relative in ("workspaces", "state", "state/codex", "state/antigravity"):
        actual = (root / relative).stat().st_mode & 0o777
        require(
            actual == 0o755,
            f"unexpected structural parent mode for {relative}: {oct(actual)}",
        )

    for spec in CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS:
        actual = (root / spec.suffix).stat().st_mode & 0o777
        require(
            actual == spec.mode,
            f"unexpected initial mode for {spec.suffix}: {oct(actual)} != {oct(spec.mode)}",
        )


def main() -> int:
    """Validate bootstrap/preflight safety and TrueNAS contract alignment."""
    with tempfile.TemporaryDirectory() as temporary_directory:
        base = Path(temporary_directory)
        validate_bootstrap(base / "remote-dev")
        validate_symlinks(base)
        validate_initial_modes(base / "mode-root")
    validate_compose_contract()

    print("Host data-layout bootstrap/preflight regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
