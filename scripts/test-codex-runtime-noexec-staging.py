#!/usr/bin/env python3
"""Container regression for Codex candidate execution with noexec /tmp."""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tarfile
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


def run_regression() -> int:
    if os.geteuid() != 0:
        raise AssertionError("the noexec regression must run as root")
    options = mount_options(Path("/tmp"))
    for required in ("rw", "noexec", "nosuid", "nodev"):
        if required not in options:
            raise AssertionError(f"/tmp is missing mount option {required}: {options}")

    descriptor, name = tempfile.mkstemp(
        prefix="remote-dev-noexec-control-", dir="/tmp"
    )
    control = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write("#!/bin/sh\nexit 0\n")
            output.flush()
            os.fchmod(output.fileno(), 0o755)
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

    unsafe_parent = Path(
        tempfile.mkdtemp(prefix="codex-noexec-probe-", dir="/tmp")
    )
    unsafe_parent.chmod(0o711)
    configured_staging_root = manager.STAGING_ROOT
    manager.STAGING_ROOT = unsafe_parent / "staging"
    try:
        try:
            manager.prepare_staging_root()
        except manager.ManagerError as exc:
            if "does not permit candidate execution" not in str(exc):
                raise AssertionError(f"unexpected noexec probe failure: {exc}") from exc
        else:
            raise AssertionError("the staging execution probe accepted noexec /tmp")
    finally:
        manager.STAGING_ROOT = configured_staging_root
        shutil.rmtree(unsafe_parent, ignore_errors=True)

    caller_tmp = Path(tempfile.mkdtemp(prefix="caller-controlled-codex-tmp-", dir="/tmp"))
    development_names = (
        "TMPDIR",
        "TMP",
        "TEMP",
        "UV_CACHE_DIR",
        "NPM_CONFIG_CACHE",
        "PIP_CACHE_DIR",
    )
    old_development = {name: os.environ.get(name) for name in development_names}
    os.environ.update({name: str(caller_tmp) for name in development_names})
    staging = None
    try:
        with manager.update_staging() as staging:
            if staging.parent != manager.STAGING_ROOT:
                raise AssertionError(f"unexpected staging parent: {staging.parent}")
            if staging.is_relative_to(Path("/tmp")):
                raise AssertionError(f"staging unexpectedly uses /tmp: {staging}")
            for transient in (manager.STAGING_ROOT, staging):
                info = transient.stat()
                if (info.st_uid, info.st_gid) != (0, 0):
                    raise AssertionError(f"staging has wrong owner: {transient}")
                if info.st_mode & 0o777 != 0o711:
                    raise AssertionError(f"staging has wrong mode: {transient}")
            archive_path = staging / "synthetic-candidate.tar.gz"
            candidate_content = (
                "#!/bin/sh\n"
                "groups=$(sed -n 's/^Groups:[[:space:]]*//p' /proc/self/status)\n"
                "printf '%s:%s:%s:%s:%s\\n' \"$(id -u)\" \"$(id -g)\" "
                '"$groups" "$HOME" "$(pwd -P)"\n'
            ).encode()
            with tarfile.open(archive_path, "w:gz") as archive:
                for path, content, mode in (
                    ("bin/codex", candidate_content, 0o755),
                    ("codex-resources/implicit/nested/data", b"fixture\n", 0o644),
                ):
                    info = tarfile.TarInfo(path)
                    info.mode = mode
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
            package = staging / "package"
            manager.extract(archive_path, package)
            candidate = package / "bin/codex"
            data_file = package / "codex-resources/implicit/nested/data"
            for directory in (
                package,
                package / "bin",
                package / "codex-resources",
                package / "codex-resources/implicit",
                package / "codex-resources/implicit/nested",
            ):
                info = directory.stat()
                if (info.st_uid, info.st_gid) != (0, 0):
                    raise AssertionError(f"candidate directory has wrong owner: {directory}")
                if info.st_mode & 0o777 != 0o755:
                    raise AssertionError(f"candidate directory has wrong mode: {directory}")
            if (candidate.stat().st_uid, candidate.stat().st_gid) != (0, 0):
                raise AssertionError("candidate executable is not root-owned")
            if candidate.stat().st_mode & 0o777 != 0o755:
                raise AssertionError("candidate executable is not mode 0755")
            if (data_file.stat().st_uid, data_file.stat().st_gid) != (0, 0):
                raise AssertionError("candidate data file is not root-owned")
            if data_file.stat().st_mode & 0o777 != 0o644:
                raise AssertionError("candidate data file is not mode 0644")
            home, cwd = manager.prepare_candidate_directories(staging)
            for private in (home, cwd):
                info = private.stat()
                if info.st_uid != manager.NOBODY or info.st_gid != manager.NOBODY:
                    raise AssertionError(f"synthetic state has wrong owner: {private}")
                if info.st_mode & 0o777 != 0o700:
                    raise AssertionError(f"synthetic state has wrong mode: {private}")
            result = manager.candidate_run([str(candidate)], cwd, home)
            expected = f"{manager.NOBODY}:{manager.NOBODY}::{home}:{cwd}"
            if result.returncode != 0 or result.stdout.strip() != expected:
                raise AssertionError(
                    f"candidate identity/state mismatch: {result.returncode} {result.stdout!r}"
                )
    finally:
        active_error = sys.exception()
        for name, old_value in old_development.items():
            if old_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old_value
        leaked = sorted(entry.name for entry in caller_tmp.iterdir())
        shutil.rmtree(caller_tmp, ignore_errors=True)
        if leaked:
            message = f"staging honoured caller development environment; leaked entries: {leaked}"
            if active_error is None:
                raise AssertionError(message)
            active_error.add_note(message)

    if staging is None or staging.exists():
        raise AssertionError("Codex update staging was not cleaned")
    if any(manager.STAGING_ROOT.iterdir()):
        raise AssertionError("Codex update staging root contains leftovers")
    print("Codex runtime noexec /tmp staging regression: OK")
    return 0


def main() -> int:
    previous_umask = os.umask(0o077)
    try:
        return run_regression()
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
