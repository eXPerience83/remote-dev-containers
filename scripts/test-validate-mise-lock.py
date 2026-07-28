#!/usr/bin/env python3
"""Exercise fail-closed mise configuration and lockfile validation cases."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

INPUT_FILES = ("versions.env", "mise.toml", "mise.lock")


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace one required text fragment or fail the test setup."""
    content = path.read_text(encoding="utf-8")
    if old not in content:
        raise AssertionError(f"test fixture fragment not found in {path}: {old!r}")
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def append_text(path: Path, text: str) -> None:
    """Append text to one copied fixture file."""
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def run_validator(validator: Path, root: Path) -> subprocess.CompletedProcess[str]:
    """Run the validator against one isolated fixture root."""
    return subprocess.run(
        [sys.executable, str(validator), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def copied_fixture(source_root: Path, destination: Path) -> None:
    """Copy the repository-controlled validator inputs into a temporary root."""
    for relative_path in INPUT_FILES:
        shutil.copy2(source_root / relative_path, destination / relative_path)


def expect_failure(
    source_root: Path,
    validator: Path,
    name: str,
    mutate: Callable[[Path], None],
    expected_message: str,
) -> None:
    """Require one malicious or malformed fixture to be rejected."""
    with tempfile.TemporaryDirectory(prefix="mise-lock-test-") as temp_dir:
        fixture_root = Path(temp_dir)
        copied_fixture(source_root, fixture_root)
        mutate(fixture_root)
        result = run_validator(validator, fixture_root)
        if result.returncode == 0:
            raise AssertionError(f"{name}: validator unexpectedly accepted the fixture")
        if expected_message not in result.stderr:
            raise AssertionError(
                f"{name}: expected {expected_message!r} in stderr, got:\n{result.stderr}"
            )
    print(f"OK reject {name}")


def parse_args() -> argparse.Namespace:
    """Parse an optional repository root for CI and local execution."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    return parser.parse_args()


def main() -> int:
    """Validate the real inputs and a set of adversarial mutations."""
    source_root = parse_args().root.resolve()
    validator = source_root / "scripts/validate-mise-lock.py"

    baseline = run_validator(validator, source_root)
    if baseline.returncode != 0:
        raise AssertionError(f"baseline validation failed:\n{baseline.stderr}")
    print("OK accept committed mise inputs")

    expect_failure(
        source_root,
        validator,
        "unexpected mise.toml section",
        lambda root: append_text(root / "mise.toml", '\n[env]\nDANGEROUS = "1"\n'),
        "mise.toml top-level keys must be exactly",
    )
    expect_failure(
        source_root,
        validator,
        "unexpected mise setting",
        lambda root: replace_once(
            root / "mise.toml",
            "lockfile = true\n",
            "lockfile = true\nexperimental = true\n",
        ),
        "mise.toml settings keys must be exactly",
    )
    expect_failure(
        source_root,
        validator,
        "runtime version drift",
        lambda root: replace_once(
            root / "mise.toml", 'python = "3.14.6"', 'python = "3.14.5"'
        ),
        "does not match versions.env",
    )
    expect_failure(
        source_root,
        validator,
        "unexpected lockfile section",
        lambda root: append_text(root / "mise.lock", '\n[metadata]\nowner = "attacker"\n'),
        "mise.lock top-level keys must be exactly",
    )
    expect_failure(
        source_root,
        validator,
        "extra platform scalar",
        lambda root: replace_once(
            root / "mise.lock",
            'backend = "core:node"\n\n',
            'backend = "core:node"\n"platforms.linux-x64-musl" = "malformed"\n\n',
        ),
        "mise.lock tools.node keys must be exactly",
    )
    expect_failure(
        source_root,
        validator,
        "required platform scalar",
        lambda root: replace_once(
            root / "mise.lock",
            '[tools.node."platforms.linux-arm64"]\n'
            'checksum = "sha256:6b4484c2190274175df9aa8f28e2d758a819cb1c1fe6ab481e2f95b463ab8508"\n'
            'url = "https://nodejs.org/dist/v24.18.0/node-v24.18.0-linux-arm64.tar.gz"\n',
            '"platforms.linux-arm64" = "malformed"\n',
        ),
        "no valid node artifact mapping for linux-arm64",
    )
    expect_failure(
        source_root,
        validator,
        "unexpected artifact field",
        lambda root: replace_once(
            root / "mise.lock",
            'checksum = "sha256:6b4484c2190274175df9aa8f28e2d758a819cb1c1fe6ab481e2f95b463ab8508"\n',
            'checksum = "sha256:6b4484c2190274175df9aa8f28e2d758a819cb1c1fe6ab481e2f95b463ab8508"\nsize = 1\n',
        ),
        "mise.lock tools.node.linux-arm64 keys must be exactly",
    )
    expect_failure(
        source_root,
        validator,
        "untrusted uv API URL",
        lambda root: replace_once(
            root / "mise.lock",
            "https://api.github.com/repos/astral-sh/uv/releases/assets/487747547",
            "https://example.invalid/releases/assets/487747547",
        ),
        "mise.lock uv API URL for linux-arm64 is unexpected",
    )
    expect_failure(
        source_root,
        validator,
        "missing provenance",
        lambda root: replace_once(
            root / "mise.lock", 'provenance = "github-attestations"\n', ""
        ),
        "mise.lock tools.python.linux-arm64 keys must be exactly",
    )

    print("All mise lock validation tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
