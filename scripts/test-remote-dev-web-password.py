#!/usr/bin/env python3
"""Regression coverage for Remote Dev agent-terminal password source handling."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_LIB = Path(
    os.environ.get(
        "REMOTE_DEV_RUNTIME_LIB",
        ROOT / "scripts/lib/remote-dev-runtime.sh",
    )
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_file_action(action: str, path: str | Path) -> subprocess.CompletedProcess[bytes]:
    script = 'source "$1"; remote_dev_web_password_file "$2" "$3"'
    return subprocess.run(
        ["bash", "-c", script, "bash", str(RUNTIME_LIB), action, str(path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def expect_rejected(path: str | Path, label: str, forbidden: bytes = b"") -> None:
    result = run_file_action("read", path)
    require(result.returncode != 0, f"{label} unexpectedly succeeded")
    require(result.stdout == b"", f"{label} emitted password bytes")
    if forbidden:
        require(forbidden not in result.stderr, f"{label} leaked password bytes")


def auth_source(**updates: str | None) -> tuple[int, str, str]:
    env = os.environ.copy()
    for name in ("WEB_PASSWORD_FILE", "WEB_PASSWORD", "ALLOW_INSECURE_WEB"):
        env.pop(name, None)
    for name, value in updates.items():
        if value is not None:
            env[name] = value

    script = 'source "$1"; remote_dev_web_auth_source'
    result = subprocess.run(
        ["bash", "-c", script, "bash", str(RUNTIME_LIB)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr


def validate_file_contract(temporary_directory: str) -> None:
    root = Path(temporary_directory)
    password = root / "password.txt"

    password.write_bytes(b"synthetic-password")
    valid = run_file_action("read", password)
    require(valid.returncode == 0, valid.stderr.decode(errors="replace"))
    require(valid.stdout == b"synthetic-password", "valid password was changed")

    password.write_bytes(b"synthetic-password\n")
    trailing_lf = run_file_action("read", password)
    require(trailing_lf.returncode == 0, trailing_lf.stderr.decode(errors="replace"))
    require(trailing_lf.stdout == b"synthetic-password", "single trailing LF was not removed")

    check_only = run_file_action("check", password)
    require(check_only.returncode == 0, check_only.stderr.decode(errors="replace"))
    require(check_only.stdout == b"", "check action emitted password bytes")

    password.write_bytes(b"")
    expect_rejected(password, "empty password")

    password.write_bytes(b"\n")
    expect_rejected(password, "newline-only password")

    password.write_bytes(b"synthetic-password\n\n")
    expect_rejected(password, "multiple trailing newlines", b"synthetic-password")

    password.write_bytes(b"synthetic-password\nsecond-line\n")
    expect_rejected(password, "multiline password", b"synthetic-password")

    password.write_bytes(b"synthetic-password\r\n")
    expect_rejected(password, "CRLF password", b"synthetic-password")

    password.write_bytes(b"synthetic-password\x00suffix")
    expect_rejected(password, "NUL password", b"synthetic-password")

    password.write_bytes(b"synthetic-password\n")
    password.chmod(0o644)
    runtime_mode = run_file_action("check", password)
    require(
        runtime_mode.returncode == 0,
        "runtime resolver must not reject Docker/Compose rematerialized secret modes; host preflight owns source-file mode",
    )

    missing = root / "missing.txt"
    expect_rejected(missing, "missing password")

    directory = root / "password-directory"
    directory.mkdir()
    expect_rejected(directory, "directory password path")

    if hasattr(os, "mkfifo"):
        fifo = root / "password-fifo"
        os.mkfifo(fifo)
        expect_rejected(fifo, "FIFO password path")

    target = root / "target.txt"
    target.write_bytes(b"do-not-follow-secret\n")
    final_symlink = root / "password-link"
    final_symlink.symlink_to(target)
    expect_rejected(final_symlink, "symlinked password file", b"do-not-follow-secret")

    outside = root / "outside"
    outside.mkdir()
    outside_password = outside / "password.txt"
    outside_password.write_bytes(b"do-not-follow-secret\n")
    intermediate = root / "linked-directory"
    intermediate.symlink_to(outside, target_is_directory=True)
    expect_rejected(
        intermediate / "password.txt",
        "symlinked password ancestor",
        b"do-not-follow-secret",
    )

    relative = run_file_action("check", "relative-password")
    require(relative.returncode != 0, "relative password path unexpectedly succeeded")
    require(relative.stdout == b"", "relative password path emitted output")


def validate_source_precedence() -> None:
    code, source, stderr = auth_source(
        WEB_PASSWORD_FILE="/run/secrets/web_password",
        WEB_PASSWORD="synthetic-environment-password",
        ALLOW_INSECURE_WEB="0",
    )
    require(code == 0 and source == "file", stderr or source)

    code, source, stderr = auth_source(
        WEB_PASSWORD="synthetic-environment-password",
        ALLOW_INSECURE_WEB="0",
    )
    require(code == 0 and source == "environment", stderr or source)

    code, source, stderr = auth_source(ALLOW_INSECURE_WEB="1")
    require(code == 0 and source == "disabled", stderr or source)

    code, source, stderr = auth_source(ALLOW_INSECURE_WEB="0")
    require(code == 0 and source == "unconfigured", stderr or source)


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary_directory:
        validate_file_contract(temporary_directory)
    validate_source_precedence()
    print("Agent terminal password source regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
