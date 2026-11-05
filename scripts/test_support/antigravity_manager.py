#!/usr/bin/env python3
"""Rebind a copied Antigravity manager to an isolated, synthetic test harness.

Only test scripts call this helper. Production manager and runtime sources remain
unmodified; every reviewed replacement anchor must occur exactly once.
"""

from __future__ import annotations

from pathlib import Path
import shlex
import sys


def replace_once(text: str, old: str, new: str) -> str:
    """Reject changed or ambiguous production anchors instead of guessing."""
    if text.count(old) != 1:
        raise AssertionError(f"expected one canonical manager fixture anchor: {old}")
    return text.replace(old, new)


def prepare_manager(
    source: Path,
    destination: Path,
    paths_lib: Path,
    runtime_lib: Path,
    antigravity_lib_dir: Path,
    test_bin: Path,
    *,
    python_executable: str,
) -> None:
    """Prepare the fixture only after all path anchors have been validated."""
    integrity = antigravity_lib_dir / "integrity.sh"
    integrity_text = replace_once(
        integrity.read_text(encoding="utf-8"),
        "/usr/local/lib/remote-dev/python",
        python_executable,
    )

    manager_text = source.read_text(encoding="utf-8")
    replacements = {
        "/usr/local/lib/remote-dev/antigravity-paths.sh": shlex.quote(str(paths_lib)),
        "/usr/local/lib/remote-dev/remote-dev-runtime.sh": shlex.quote(str(runtime_lib)),
        "/usr/local/lib/remote-dev/antigravity-runtime": shlex.quote(str(antigravity_lib_dir)),
        "PATH=/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin":
            f"PATH={shlex.quote(str(test_bin))}:/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin",
    }
    for old, new in replacements.items():
        manager_text = replace_once(manager_text, old, new)

    # Never touch the production inputs, and do not write partial fixture output
    # when a source anchor is missing or duplicated.
    integrity.write_text(integrity_text, encoding="utf-8")
    destination.write_text(manager_text, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 7:
        raise SystemExit("usage: antigravity_manager.py SOURCE DEST PATHS RUNTIME LIB_DIR TEST_BIN")
    source, destination, paths_lib, runtime_lib, antigravity_lib_dir, test_bin = (
        Path(argument) for argument in sys.argv[1:]
    )
    prepare_manager(
        source, destination, paths_lib, runtime_lib, antigravity_lib_dir, test_bin,
        python_executable=sys.executable,
    )


if __name__ == "__main__":
    main()
