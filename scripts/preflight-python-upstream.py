#!/usr/bin/env python3
"""Admit an upstream CPython patch only after the pinned mise can lock both targets.

This probe is intentionally isolated from the checkout and from the grouped updater:
an expected Python artifact propagation delay must not discard unrelated updates.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import NoReturn

VERSION_RE = re.compile(r"^3\.(?:14|15)\.[0-9]+$")
PLATFORMS = ("linux-x64", "linux-arm64")
TIMEOUT_SECONDS = 600


def fail(message: str) -> NoReturn:
    raise RuntimeError(message)


def load_lock_validator():
    path = Path(__file__).resolve().with_name("validate-mise-lock.py")
    spec = importlib.util.spec_from_file_location("remote_dev_mise_lock_validator", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import lock validator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def python_patch(value: str) -> tuple[int, int, int]:
    if not VERSION_RE.fullmatch(value):
        fail(f"unexpected Python maintenance version: {value!r}")
    return tuple(map(int, value.split(".")))


def is_expected_propagation_delay(output: str, candidate: str) -> bool:
    """Only a specifically identified Python/platform resolver miss is deferrable."""
    escaped = re.escape(candidate)
    missing = re.compile(
        rf"failed to resolve python@{escaped} for linux-(?:x64|arm64)\b",
        re.IGNORECASE,
    )
    if not missing.search(output):
        return False
    error_lines = [
        line for line in output.splitlines()
        if re.search(r"\b(?:error|failed to resolve|panic|fatal)\b", line, re.I)
    ]
    if not error_lines:
        return False
    # A Python-only probe must never conceal unrelated resolver/policy failures.
    return all(missing.search(line) for line in error_lines)


def isolated_env(root: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("MISE_")
        and key not in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_PAT", "GH_ENTERPRISE_TOKEN")
    }
    for name in ("cache", "config", "data", "system", "tmp", "home"):
        (root / name).mkdir(mode=0o700)
    (root / "config" / "global.toml").write_text("", encoding="utf-8")
    (root / "system" / "config.toml").write_text("", encoding="utf-8")
    env.update({
        "HOME": str(root / "home"),
        "MISE_CACHE_DIR": str(root / "cache"),
        "MISE_CONFIG_DIR": str(root / "config"),
        "MISE_DATA_DIR": str(root / "data"),
        "MISE_GLOBAL_CONFIG_FILE": str(root / "config" / "global.toml"),
        "MISE_SYSTEM_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_FILE": str(root / "system" / "config.toml"),
        "MISE_TMP_DIR": str(root / "tmp"),
        "MISE_HTTP_TIMEOUT": "60s",
        "MISE_SAFE": "1",
        "MISE_NOT_FOUND_AUTO_INSTALL": "false",
    })
    return env


def validate_lock_header(lock: dict) -> None:
    """Accept only reviewed mise lock formats, including a legacy absent header."""
    keys = set(lock)
    if keys not in ({"tools"}, {"lockfile_version", "tools"}):
        fail(f"probe produced unexpected top-level mise.lock keys: {sorted(keys)}")
    if "lockfile_version" in lock:
        version = lock["lockfile_version"]
        if type(version) is not int or version not in (1, 2, 3):
            fail(f"probe lockfile version is not supported: {version!r}")


def seed_reviewed_python_lock(destination: Path, current: str) -> None:
    """Seed the current valid Python platforms to trigger genuine mise regression errors.

    A fresh first lock may skip missing artifacts without a fatal error. Carrying
    forward the reviewed Python-only lock causes mise to fail rather than drop
    a previously supported platform when the candidate is not yet available.
    """
    source = Path(__file__).resolve().parents[1] / "mise.lock"
    try:
        content = source.read_text(encoding="utf-8")
        lock = tomllib.loads(content)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"cannot read reviewed mise.lock for Python admission: {exc}")
    validate_lock_header(lock)
    tools = lock.get("tools")
    if not isinstance(tools, dict) or not isinstance(tools.get("python"), list):
        fail("reviewed mise.lock has no Python tool entries")

    validator = load_lock_validator()
    reviewed = [entry for entry in tools["python"] if entry.get("version") == current]
    if len(reviewed) != 1:
        fail(f"reviewed mise.lock must contain exactly one Python {current} entry")
    validator.validate_tool_entry("python", current, reviewed)

    sections = re.findall(
        r"(?ms)^\[\[tools\.python\]\]\n.*?(?=^\[\[tools\.|\Z)",
        content,
    )
    matching_sections = [
        section for section in sections
        if tomllib.loads(section)["tools"]["python"][0]["version"] == current
    ]
    if len(matching_sections) != 1:
        fail(f"cannot select exactly one Python {current} lock section")
    header = (
        f"lockfile_version = {lock['lockfile_version']}\n\n"
        if "lockfile_version" in lock else ""
    )
    destination.write_text(
        "# Generated from the verified committed Python lock entry.\n"
        + header + matching_sections[0],
        encoding="utf-8",
    )


def validate_python_only_lock(path: Path, candidate: str) -> None:
    validator = load_lock_validator()
    try:
        with path.open("rb") as handle:
            lock = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        fail(f"probe did not produce a valid mise.lock: {exc}")
    validate_lock_header(lock)
    if not isinstance(lock["tools"], dict) or set(lock["tools"]) != {"python"}:
        fail("probe lock unexpectedly contains tools other than Python")
    # Reuse the exact accepted backend, URL, SHA-256 and attestations policy.
    validator.validate_tool_entry("python", candidate, lock["tools"]["python"])


def select_python_version(current: str, candidate: str, mise_bin: Path) -> str:
    current_patch = python_patch(current)
    candidate_patch = python_patch(candidate)
    if candidate_patch[:2] != current_patch[:2]:
        fail(f"Python updater cannot change maintenance lines: {current} -> {candidate}")
    if candidate_patch < current_patch:
        fail(f"Python upstream candidate {candidate} is older than reviewed {current}")
    if candidate == current:
        return current
    if not mise_bin.is_file() or not os.access(mise_bin, os.X_OK):
        fail(f"verified mise binary is missing or not executable: {mise_bin}")

    with tempfile.TemporaryDirectory(prefix="remote-dev-python-upstream-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        workspace.mkdir(mode=0o700)
        config = (
            '[settings]\n'
            'lockfile = true\n'
            'locked_verify_provenance = true\n'
            'lockfile_platforms = ["linux-x64", "linux-arm64"]\n\n'
            '[tools]\n'
            f'python = "{candidate}"\n'
        )
        (workspace / "mise.toml").write_text(config, encoding="utf-8")
        seed_reviewed_python_lock(workspace / "mise.lock", current)
        try:
            result = subprocess.run(
                [str(mise_bin.resolve()), "lock", "--platform", ",".join(PLATFORMS)],
                cwd=workspace,
                env=isolated_env(root),
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            fail(f"Python upstream mise probe could not complete: {exc}")

        output = result.stdout + "\n" + result.stderr
        if result.returncode != 0:
            if is_expected_propagation_delay(output, candidate):
                print(
                    f"Python {candidate} is released but not yet lockable on all "
                    f"Remote Dev platforms; retaining reviewed {current}.",
                    file=sys.stderr,
                )
                return current
            fail(
                f"unexpected Python upstream resolver failure (exit {result.returncode}); "
                f"failing closed:\n{output[-2500:]}"
            )

        validate_python_only_lock(workspace / "mise.lock", candidate)
        print(
            f"Python {candidate}: exact {','.join(PLATFORMS)} artifacts pass "
            "the reviewed lock policy.",
            file=sys.stderr,
        )
        return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--mise-bin", required=True, type=Path)
    args = parser.parse_args()
    try:
        selected = select_python_version(args.current, args.candidate, args.mise_bin)
    except (RuntimeError, SystemExit) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
