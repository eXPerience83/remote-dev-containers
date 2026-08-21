#!/usr/bin/env python3
"""Container regression for Codex candidate execution with noexec /tmp."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

MANAGER = Path(
    os.environ.get(
        "REMOTE_DEV_CODEX_RUNTIME_MANAGER",
        Path(__file__).with_name("remote-dev-codex-runtime.py"),
    )
)


def load_manager():
    loader = SourceFileLoader("codex_runtime_noexec", str(MANAGER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {MANAGER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def mount_options(path: Path) -> set[str]:
    for line in Path("/proc/mounts").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1] == str(path):
            return set(fields[3].split(","))
    raise AssertionError(f"{path} is not an explicit mount")


def main() -> int:
    if os.geteuid() != 0:
        raise AssertionError("the noexec regression must run as root")
    options = mount_options(Path("/tmp"))
    for required in ("rw", "noexec", "nosuid", "nodev"):
        if required not in options:
            raise AssertionError(f"/tmp is missing mount option {required}: {options}")

    control = Path(f"/tmp/remote-dev-noexec-control-{os.getpid()}")
    control.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    control.chmod(0o755)
    try:
        try:
            subprocess.run([str(control)], check=True)
        except PermissionError:
            pass
        else:
            raise AssertionError("the /tmp executable control unexpectedly ran")
    finally:
        control.unlink(missing_ok=True)

    manager = load_manager()
    if manager.STAGING_ROOT.is_relative_to(Path("/tmp")):
        raise AssertionError("Codex update staging remains below /tmp")

    caller_tmp = Path(tempfile.mkdtemp(prefix="caller-controlled-codex-tmp-", dir="/tmp"))
    old_tmpdir = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(caller_tmp)
    staging = None
    try:
        with manager.update_staging() as staging:
            if staging.parent != manager.STAGING_ROOT:
                raise AssertionError(f"unexpected staging parent: {staging.parent}")
            package_bin = staging / "package" / "bin"
            package_bin.mkdir(parents=True)
            (staging / "package").chmod(0o755)
            package_bin.chmod(0o755)
            candidate = package_bin / "codex"
            candidate.write_text(
                "#!/bin/sh\n"
                "printf '%s:%s:%s:%s\\n' \"$(id -u)\" \"$(id -g)\" "
                '"$HOME" "$(pwd -P)"\n',
                encoding="utf-8",
            )
            candidate.chmod(0o755)
            home, cwd = manager.prepare_candidate_directories(staging)
            for private in (home, cwd):
                info = private.stat()
                if info.st_uid != manager.NOBODY or info.st_gid != manager.NOBODY:
                    raise AssertionError(f"synthetic state has wrong owner: {private}")
                if info.st_mode & 0o777 != 0o700:
                    raise AssertionError(f"synthetic state has wrong mode: {private}")
            result = manager.candidate_run([str(candidate)], cwd, home)
            expected = f"{manager.NOBODY}:{manager.NOBODY}:{home}:{cwd}"
            if result.returncode != 0 or result.stdout.strip() != expected:
                raise AssertionError(
                    f"candidate identity/state mismatch: {result.returncode} {result.stdout!r}"
                )
    finally:
        if old_tmpdir is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = old_tmpdir
        caller_tmp.rmdir()

    if staging is None or staging.exists():
        raise AssertionError("Codex update staging was not cleaned")
    if any(manager.STAGING_ROOT.iterdir()):
        raise AssertionError("Codex update staging root contains leftovers")
    print("Codex runtime noexec /tmp staging regression: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
