#!/usr/bin/env python3
"""Admit a new mise only if its real locked Python bootstrap works in safe mode.

A known new-release locked-lookup regression defers *only mise*. Other failures
(network, integrity, provenance, malformed lock) fail closed. No repo writes.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION_RE = re.compile(r"^[0-9]{4}\.[0-9]+\.[0-9]+$")
PYTHON_RE = re.compile(r"^3\.14\.[0-9]+$")
TIMEOUT_SECONDS = 600


def known_safe_mode_lookup_regression(output: str, python_version: str) -> bool:
    """Only classify the observed exact Python locked lookup errors as deferrable."""
    escaped = re.escape(python_version)
    expected = re.compile(
        rf"(?:No lockfile URL found for python@{escaped} on platform linux-x64 "
        rf"\(--locked mode\)|python@{escaped} is not in the lockfile)",
        re.IGNORECASE,
    )
    errors: list[str] = []
    for line in output.splitlines():
        if re.search(r"\bERROR (?:Version:|Run with)\b", line):
            continue  # Mise's diagnostic footer, not a second failure.
        if re.search(r"\bERROR\b|\bfailed:", line, re.IGNORECASE):
            errors.append(line)
    return bool(errors) and all(expected.search(line) for line in errors)


def isolated_env(root: Path) -> dict[str, str]:
    for name in ("home", "cache", "config", "data", "system", "tmp"):
        (root / name).mkdir(mode=0o700)
    (root / "config" / "global.toml").write_text("", encoding="utf-8")
    (root / "system" / "config.toml").write_text("", encoding="utf-8")
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root / "home"),
        "MISE_CACHE_DIR": str(root / "cache"),
        "MISE_CONFIG_DIR": str(root / "config"),
        "MISE_DATA_DIR": str(root / "data"),
        "MISE_SYSTEM_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_FILE": str(root / "system" / "config.toml"),
        "MISE_GLOBAL_CONFIG_FILE": str(root / "config" / "global.toml"),
        "MISE_TMP_DIR": str(root / "tmp"),
        "MISE_SAFE": "1",
        "MISE_PYTHON_COMPILE": "false",
        "MISE_HTTP_TIMEOUT": "60s",
        "UV_PYTHON_DOWNLOADS": "never",
    }


def run_mise(binary: Path, root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(binary), *args],
        cwd=root / "bootstrap",
        env=isolated_env_existing(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT_SECONDS,
    )


def isolated_env_existing(root: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(root / "home"),
        "MISE_CACHE_DIR": str(root / "cache"),
        "MISE_CONFIG_DIR": str(root / "config"),
        "MISE_DATA_DIR": str(root / "data"),
        "MISE_SYSTEM_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_DIR": str(root / "system"),
        "MISE_SYSTEM_CONFIG_FILE": str(root / "system" / "config.toml"),
        "MISE_GLOBAL_CONFIG_FILE": str(root / "config" / "global.toml"),
        "MISE_TMP_DIR": str(root / "tmp"),
        "MISE_SAFE": "1",
        "MISE_PYTHON_COMPILE": "false",
        "MISE_HTTP_TIMEOUT": "60s",
        "UV_PYTHON_DOWNLOADS": "never",
    }


def select_mise(current: str, candidate: str, mise_bin: Path, python_version: str) -> str:
    if not VERSION_RE.fullmatch(current) or not VERSION_RE.fullmatch(candidate):
        raise ValueError("mise versions must be exact stable releases")
    if not PYTHON_RE.fullmatch(python_version):
        raise ValueError("unexpected exact administrative Python version")
    if candidate == current:
        return current
    if not mise_bin.is_file() or not os.access(mise_bin, os.X_OK):
        raise ValueError("verified candidate mise binary is missing or non-executable")

    with tempfile.TemporaryDirectory(prefix="remote-dev-mise-admission-") as temp:
        root = Path(temp)
        env = isolated_env(root)
        bootstrap = root / "bootstrap"
        bootstrap.mkdir(mode=0o700)
        (bootstrap / "mise.toml").write_text(
            '[settings]\n'
            'lockfile = true\n'
            'locked_verify_provenance = true\n'
            'lockfile_platforms = ["linux-x64", "linux-arm64"]\n\n'
            '[tools]\n'
            f'python = "{python_version}"\n',
            encoding="utf-8",
        )
        lock = subprocess.run(
            [str(mise_bin), "lock", "--platform", "linux-x64,linux-arm64"],
            cwd=bootstrap,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        if lock.returncode != 0:
            raise RuntimeError(
                f"candidate mise lock failed (exit {lock.returncode}): "
                f"{(lock.stdout + lock.stderr)[-1800:]}"
            )
        validator = Path(__file__).resolve().with_name("validate-mise-bootstrap-lock.py")
        validated = subprocess.run(
            [sys.executable, str(validator), "--lock", str(bootstrap / "mise.lock"),
             "--python-version", python_version],
            cwd=bootstrap,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if validated.returncode:
            raise RuntimeError(
                "candidate mise emitted an unreviewed or incomplete lock: "
                f"{validated.stderr[-1600:]}"
            )

        installed = subprocess.run(
            [str(mise_bin), "install", "--locked"],
            cwd=bootstrap,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        output = installed.stdout + "\n" + installed.stderr
        if installed.returncode:
            if known_safe_mode_lookup_regression(output, python_version):
                print(
                    f"DEFER mise {candidate}: locked Python bootstrap is incompatible "
                    f"with MISE_SAFE=1; keep reviewed mise {current}.",
                    file=sys.stderr,
                )
                return current
            raise RuntimeError(
                f"unexpected candidate mise installation failure "
                f"(exit {installed.returncode}): {output[-1800:]}"
            )
        where = run_mise(mise_bin, root, ["where", f"python@{python_version}"])
        if where.returncode:
            raise RuntimeError("candidate mise cannot locate installed Python")
        py_dir = Path(where.stdout.strip()).resolve()
        if not py_dir.is_relative_to((root / "data").resolve()):
            raise RuntimeError("candidate mise installed Python outside isolated data")
        py = subprocess.run(
            [str(py_dir / "bin" / "python3"), "--version"],
            cwd=bootstrap, env=env, capture_output=True, text=True, check=False,
            timeout=20,
        )
        if py.returncode or py.stdout.strip() != f"Python {python_version}":
            raise RuntimeError("candidate mise did not install the exact reviewed Python")
        print(f"ADMIT mise {candidate}: safe locked Python bootstrap passed.", file=sys.stderr)
        return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--mise-bin", required=True, type=Path)
    parser.add_argument("--python-version", required=True)
    args = parser.parse_args()
    try:
        selected = select_mise(
            args.current, args.candidate, args.mise_bin.resolve(), args.python_version
        )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())
