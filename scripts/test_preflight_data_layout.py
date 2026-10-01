#!/usr/bin/env python3
"""Exercise the canonical host-side Remote Dev data-layout bootstrap and preflight."""

from __future__ import annotations

import os
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
    initialize_layout,
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

    specs = CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS
    for spec in specs:
        directory = root / spec.suffix
        (directory / "existing-state.txt").write_text("preserve", encoding="utf-8")
        directory.chmod(0o750)  # Existing operator policy must survive reruns.
    rerun = run_script(BOOTSTRAP, root, include_antigravity=True)
    require(rerun.returncode == 0, rerun.stderr)
    for spec in specs:
        directory = root / spec.suffix
        require(
            (directory / "existing-state.txt").read_text(encoding="utf-8") == "preserve",
            f"bootstrap changed existing contents of {spec.suffix}",
        )
        require(
            directory.stat().st_mode & 0o777 == 0o750,
            f"bootstrap changed existing mode of {spec.suffix}",
        )


def validate_invalid_existing_component(base: Path) -> None:
    """Reject malformed existing layout before creating any missing paths."""
    for index, spec in enumerate(CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS):
        root = base / f"invalid-object-root-{index}"
        invalid = root / spec.suffix
        invalid.parent.mkdir(parents=True)
        invalid.write_text("not-a-directory", encoding="utf-8")
        before = set(root.rglob("*"))
        for script in (BOOTSTRAP, PREFLIGHT):
            result = run_script(script, root, include_antigravity=True)
            require(result.returncode == 1, f"{script.name}: {spec.suffix} must fail")
            require("not a directory" in result.stderr, result.stderr)
            require(set(root.rglob("*")) == before, "invalid layout was mutated")
            require(invalid.read_text(encoding="utf-8") == "not-a-directory", "invalid object changed")


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

    for index, spec in enumerate(CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS):
        root = base / f"leaf-symlink-root-{index}"
        linked = root / spec.suffix
        linked.parent.mkdir(parents=True)
        linked.symlink_to(outside, target_is_directory=True)
        before = set(root.rglob("*"))
        for script in (BOOTSTRAP, PREFLIGHT):
            result = run_script(script, root, include_antigravity=True)
            require(result.returncode == 1, f"{script.name}: symlink {spec.suffix} must fail")
            require("must not be a symlink" in result.stderr, result.stderr)
            require(set(root.rglob("*")) == before, "symlink layout was mutated")
            require(list(outside.iterdir()) == [], "symlink target was mutated")


def validate_required_leaves(root: Path) -> None:
    """Preflight must require every canonical leaf, including private mise state."""
    root.mkdir()
    initialize_layout(root, include_antigravity=True)
    for spec in CODEX_DIRECTORY_SPECS + ANTIGRAVITY_DIRECTORY_SPECS:
        directory = root / spec.suffix
        directory.rmdir()
        result = run_script(PREFLIGHT, root, include_antigravity=True)
        require(result.returncode == 1, f"preflight accepted missing {spec.suffix}")
        require(str(directory) in result.stderr, result.stderr)
        directory.mkdir(mode=spec.mode)


def validate_mise_specs() -> None:
    """Pin the two reviewed mise leaves without introducing shared state."""
    for role, specs in (("codex", CODEX_DIRECTORY_SPECS), ("antigravity", ANTIGRAVITY_DIRECTORY_SPECS)):
        mise = [spec for spec in specs if spec.target == "/root/.local/state/mise"]
        require(len(mise) == 1, f"{role} must have exactly one mise state leaf")
        require(mise[0].suffix == f"state/{role}/mise", f"{role} mise suffix")
        require(mise[0].mode == 0o700, f"{role} mise initial mode")
    suffixes = expected_suffixes(include_antigravity=True)
    require("state/mise" not in suffixes, "shared mise state was introduced")


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
    """Apply intentional modes exactly, independent of the caller's umask."""
    root.mkdir()
    previous_umask = os.umask(0o077)
    try:
        initialize_layout(root, include_antigravity=True)
    finally:
        os.umask(previous_umask)

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
        validate_invalid_existing_component(base)
        validate_symlinks(base)
        validate_initial_modes(base / "mode-root")
        validate_required_leaves(base / "required-root")
    validate_mise_specs()
    validate_compose_contract()

    print("Host data-layout bootstrap/preflight regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
