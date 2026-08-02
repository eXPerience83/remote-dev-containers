#!/usr/bin/env python3
"""Inspect approved Antigravity CLI installer bytes in an ephemeral home.

The report contains only a fixed normalized schema of hashes, exit codes,
allowlisted booleans and safe filesystem metadata. Vendor stdout/stderr is never
stored, printed or uploaded.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import mimetypes
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

OFFICIAL_INSTALLER_URL = "https://antigravity.google/cli/install.sh"
EXPECTED_BINARY = Path(".local/bin/agy")
PROFILE_FILES = (
    ".bashrc",
    ".bash_profile",
    ".profile",
    ".zshrc",
    ".config/fish/config.fish",
)
LEGAL_NAME_RE = re.compile(
    r"^(?:LICENSE(?:[._-].*)?|COPYING(?:[._-].*)?|NOTICE(?:[._-].*)?|"
    r"COPYRIGHT(?:[._-].*)?|AUTHORS(?:[._-].*)?)$",
    re.IGNORECASE,
)
SAFE_RELATIVE_PATH_RE = re.compile(r"[A-Za-z0-9._+/@=-]{1,300}")
SAFE_VERSION_RE = re.compile(
    r"(?<![0-9A-Za-z])([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)(?![0-9A-Za-z])"
)
SAFE_LIBRARY_RE = re.compile(r"lib[A-Za-z0-9_.+-]*\.so(?:\.[0-9]+)*")
KNOWN_SYSTEM_LIBRARIES = {
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
}


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without loading a large vendor binary into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path_identity(path: Path, root: Path) -> dict[str, Any]:
    """Return a safe path or only its hash when a name is not allowlisted."""
    relative = path.relative_to(root).as_posix()
    parts = relative.split("/")
    if (
        relative
        and all(part not in {"", ".", ".."} for part in parts)
        and all(SAFE_RELATIVE_PATH_RE.fullmatch(part) for part in parts)
    ):
        return {"path": relative, "path_redacted": False}
    return {
        "path_sha256": sha256_bytes(relative.encode("utf-8", errors="surrogateescape")),
        "path_redacted": True,
    }


def file_record(path: Path, root: Path) -> dict[str, Any]:
    """Return normalized metadata for one filesystem object, never its content."""
    metadata = path.lstat()
    record: dict[str, Any] = {
        **safe_path_identity(path, root),
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
    }
    if path.is_symlink():
        target = os.readlink(path)
        record.update(
            {
                "type": "symlink",
                "target_sha256": sha256_bytes(target.encode(errors="surrogateescape")),
                "target_is_absolute": os.path.isabs(target),
            }
        )
    elif path.is_dir():
        record["type"] = "directory"
    elif path.is_file():
        record.update(
            {
                "type": "file",
                "size": metadata.st_size,
                "sha256": sha256_file(path),
            }
        )
    else:
        record["type"] = "other"
    return record


def snapshot(root: Path) -> list[dict[str, Any]]:
    """Return a deterministic metadata-only snapshot of a directory tree."""
    if not root.exists():
        return []
    return [
        file_record(path, root)
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
    ]


def profile_snapshot(home: Path) -> dict[str, dict[str, Any] | None]:
    """Fingerprint the fixed shell-profile set without preserving contents."""
    result: dict[str, dict[str, Any] | None] = {}
    for relative in PROFILE_FILES:
        path = home / relative
        result[relative] = file_record(path, home) if path.exists() else None
    return result


def run(
    command: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded command without a shell and capture output transiently."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return subprocess.CompletedProcess(command, 124, stdout, stderr)


def command_metadata(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Record only exit status and output hashes, never vendor-controlled text."""
    return {
        "exit_code": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout.encode()),
        "stderr_sha256": sha256_bytes(completed.stderr.encode()),
    }


def extract_reported_version(completed: subprocess.CompletedProcess[str]) -> str | None:
    """Extract one conservative semantic version from transient process output."""
    versions = sorted(set(SAFE_VERSION_RE.findall(f"{completed.stdout}\n{completed.stderr}")))
    return versions[0] if len(versions) == 1 else None


def installer_options(completed: subprocess.CompletedProcess[str]) -> dict[str, bool]:
    """Detect only the reviewed option names from transient installer help."""
    help_text = f"{completed.stdout}\n{completed.stderr}"
    return {
        "custom_directory": bool(
            re.search(r"(?m)^\s*(?:-d\s*,\s*)?--dir(?:\s|=|<|$)", help_text)
        ),
        "skip_aliases": bool(
            re.search(r"(?m)^\s*--skip-aliases(?:\s|=|$)", help_text)
        ),
        "skip_path": bool(re.search(r"(?m)^\s*--skip-path(?:\s|=|$)", help_text)),
    }


def tool_result(command: list[str], env: dict[str, str], cwd: Path) -> tuple[dict[str, Any], str]:
    """Run an optional local inspection tool and retain text only in memory."""
    executable = shutil.which(command[0], path=env["PATH"])
    if executable is None:
        return {"available": False}, ""
    completed = run([executable, *command[1:]], env=env, cwd=cwd)
    return {"available": True, **command_metadata(completed)}, f"{completed.stdout}\n{completed.stderr}"


def normalize_binary_format(file_text: str, readelf_text: str) -> dict[str, Any]:
    """Convert file/readelf output into fixed booleans and a safe interpreter."""
    lowered = file_text.lower()
    interpreter_match = re.search(
        r"Requesting program interpreter:\s*([/A-Za-z0-9._+-]{1,200})",
        readelf_text,
    )
    return {
        "elf_64_bit": "elf 64-bit" in lowered,
        "x86_64": "x86-64" in lowered or "advanced micro devices x86-64" in readelf_text.lower(),
        "pie": "pie executable" in lowered,
        "dynamically_linked": "dynamically linked" in lowered,
        "stripped": "stripped" in lowered and "not stripped" not in lowered,
        "interpreter": interpreter_match.group(1) if interpreter_match else None,
    }


def normalize_dynamic_libraries(ldd_text: str) -> dict[str, Any]:
    """Expose only known system-library names and a count of unknown entries."""
    discovered = set(SAFE_LIBRARY_RE.findall(ldd_text))
    recognized = sorted(discovered & KNOWN_SYSTEM_LIBRARIES)
    return {
        "recognized": recognized,
        "unrecognized_count": len(discovered - KNOWN_SYSTEM_LIBRARIES),
    }


def verify_binary_before_execution(
    binary: Path,
    *,
    expected_sha256: str | None,
    fixture: bool,
) -> str:
    """Reject a changed vendor payload before invoking the installed executable."""
    actual_sha256 = sha256_file(binary)
    if not fixture and expected_sha256 is None:
        raise RuntimeError("official inspection requires --expected-binary-sha256")
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise RuntimeError(
            "installed binary SHA-256 differs from the reviewed value: "
            f"{actual_sha256} != {expected_sha256}"
        )
    return actual_sha256


def inspect_binary(
    binary: Path,
    env: dict[str, str],
    cwd: Path,
    *,
    expected_sha256: str | None,
    fixture: bool,
) -> dict[str, Any]:
    """Verify and inspect the executable without authentication."""
    binary_sha256 = verify_binary_before_execution(
        binary,
        expected_sha256=expected_sha256,
        fixture=fixture,
    )
    version = run([str(binary), "--version"], env=env, cwd=cwd, timeout=30)
    help_result = run([str(binary), "--help"], env=env, cwd=cwd, timeout=30)
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    file_meta, file_text = tool_result(["file", "-b", str(binary)], env, cwd)
    readelf_meta, readelf_text = tool_result(["readelf", "-l", str(binary)], env, cwd)
    ldd_meta, ldd_text = tool_result(["ldd", str(binary)], env, cwd)
    return {
        "path": EXPECTED_BINARY.as_posix(),
        "size": binary.stat().st_size,
        "sha256": binary_sha256,
        "version": {
            **command_metadata(version),
            "reported_version": extract_reported_version(version),
        },
        "help": {
            **command_metadata(help_result),
            "mentions_update_subcommand": bool(
                re.search(r"(?m)^\s*update(?:\s|$)", help_text)
            ),
            "mentions_install_subcommand": bool(
                re.search(r"(?m)^\s*install(?:\s|$)", help_text)
            ),
            "mentions_sandbox_flag": "--sandbox" in help_text,
            "mentions_skip_permissions_flag": "--dangerously-skip-permissions" in help_text,
        },
        "file_tool": file_meta,
        "readelf_tool": readelf_meta,
        "ldd_tool": ldd_meta,
        "format": normalize_binary_format(file_text, readelf_text),
        "dynamic_libraries": normalize_dynamic_libraries(ldd_text),
    }


def legal_files(home: Path) -> list[dict[str, Any]]:
    """List license-like installed files using only normalized file metadata."""
    records = []
    for path in home.rglob("*"):
        if path.is_file() and LEGAL_NAME_RE.fullmatch(path.name):
            records.append(file_record(path, home))
    return sorted(records, key=lambda item: json.dumps(item, sort_keys=True))


def inspection_environment(home: Path) -> dict[str, str]:
    """Construct a minimal credential-free environment for vendor processes."""
    return {
        "HOME": str(home),
        "USER": "inspector",
        "LOGNAME": "inspector",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "xterm-256color",
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "AGY_CLI_DISABLE_AUTO_UPDATE": "true",
        "CI": "1",
    }


def download_installer(destination: Path) -> tuple[bytes, str | None, str]:
    """Download at most 2 MiB from the fixed official HTTPS origin."""
    expected = urllib.parse.urlparse(OFFICIAL_INSTALLER_URL)
    request = urllib.request.Request(
        OFFICIAL_INSTALLER_URL,
        headers={"User-Agent": "remote-dev-containers-antigravity-inspection"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            final_url = response.geturl()
            final = urllib.parse.urlparse(final_url)
            if (
                final.scheme != "https"
                or final.hostname != expected.hostname
                or final.port not in {None, 443}
            ):
                raise RuntimeError("installer redirect left the official HTTPS origin")
            data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise RuntimeError("installer exceeds the 2 MiB inspection limit")
            destination.write_bytes(data)
            return data, response.headers.get_content_type(), final_url
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"cannot download official installer: {error}") from error


def load_local_installer(source: Path, destination: Path) -> tuple[bytes, str | None, str]:
    """Copy a local fixture for offline regression tests only."""
    data = source.read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise RuntimeError("local installer fixture exceeds the 2 MiB limit")
    destination.write_bytes(data)
    return data, mimetypes.guess_type(source.name)[0], f"fixture:{source.name}"


def verify_installer_before_execution(
    data: bytes,
    *,
    expected_sha256: str,
    final_url: str,
    fixture: bool,
) -> str:
    """Reject changed bytes or redirects before any vendor code is invoked."""
    actual_sha256 = sha256_bytes(data)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            "installer SHA-256 differs from the reviewed value: "
            f"{actual_sha256} != {expected_sha256}"
        )
    if not fixture and final_url != OFFICIAL_INSTALLER_URL:
        raise RuntimeError("official installer redirected unexpectedly")
    return actual_sha256


def choose_install_command(
    installer: Path,
    options: dict[str, bool],
    home: Path,
) -> tuple[str, list[str]]:
    """Choose only one reviewed installation strategy from normalized options."""
    base = ["/bin/bash", str(installer)]
    if options["custom_directory"]:
        return "custom-directory", [*base, "--dir", str(home / EXPECTED_BINARY.parent)]
    if options["skip_aliases"] and options["skip_path"]:
        return "skip-shell-modification-flags", [*base, "--skip-aliases", "--skip-path"]
    raise RuntimeError(
        "installer exposes neither --dir nor the reviewed skip-aliases/skip-path pair"
    )


def install_result(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Normalize installer output into a small fixed set of reviewed booleans."""
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    return {
        **command_metadata(completed),
        "reports_linux_amd64": "linux_amd64" in output,
        "reports_checksum_verified": "checksum verified" in output,
        "reports_existing_install": "already installed" in output,
        "reports_background_self_update": "self-updates in the background" in output,
    }


def inspect(
    installer_fixture: Path | None,
    expected_installer_sha256: str | None,
    expected_binary_sha256: str | None,
) -> dict[str, Any]:
    """Perform one approved installation and repeated-install inspection."""
    with tempfile.TemporaryDirectory(prefix="antigravity-inspection-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        installer = root / "install.sh"
        fixture = installer_fixture is not None
        if fixture:
            installer_data, content_type, final_url = load_local_installer(
                installer_fixture, installer
            )
            installer_source = final_url
        else:
            if expected_installer_sha256 is None:
                raise RuntimeError("official inspection requires --expected-installer-sha256")
            if expected_binary_sha256 is None:
                raise RuntimeError("official inspection requires --expected-binary-sha256")
            installer_data, content_type, final_url = download_installer(installer)
            installer_source = OFFICIAL_INSTALLER_URL

        approved_installer_sha256 = expected_installer_sha256 or sha256_bytes(installer_data)
        installer_sha256 = verify_installer_before_execution(
            installer_data,
            expected_sha256=approved_installer_sha256,
            final_url=final_url,
            fixture=fixture,
        )
        installer.chmod(0o700)

        env = inspection_environment(home)
        before_profiles = profile_snapshot(home)
        before = snapshot(home)

        syntax = run(["/bin/bash", "-n", str(installer)], env=env, cwd=root)
        if syntax.returncode != 0:
            raise RuntimeError("approved installer is not valid Bash")

        installer_help = run(
            ["/bin/bash", str(installer), "--help"], env=env, cwd=root, timeout=30
        )
        options = installer_options(installer_help)
        after_help_profiles = profile_snapshot(home)
        after_help = snapshot(home)
        if before != after_help or before_profiles != after_help_profiles:
            raise RuntimeError("approved installer --help changed the isolated home")
        strategy, install_command = choose_install_command(installer, options, home)

        first_install_process = run(install_command, env=env, cwd=root, timeout=300)
        after_first = snapshot(home)
        after_first_profiles = profile_snapshot(home)

        binary = home / EXPECTED_BINARY
        binary_after_first = (
            inspect_binary(
                binary,
                env,
                root,
                expected_sha256=expected_binary_sha256,
                fixture=fixture,
            )
            if binary.is_file()
            else None
        )

        second_install_process = run(install_command, env=env, cwd=root, timeout=300)
        after_second = snapshot(home)
        after_second_profiles = profile_snapshot(home)
        binary_after_second = (
            inspect_binary(
                binary,
                env,
                root,
                expected_sha256=expected_binary_sha256,
                fixture=fixture,
            )
            if binary.is_file()
            else None
        )

        return {
            "schema_version": 2,
            "inspected_at_utc": dt.datetime.now(dt.timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
            "platform": {
                "system": platform.system(),
                "machine": platform.machine(),
            },
            "environment_controls": {
                "auto_update_disabled": env["AGY_CLI_DISABLE_AUTO_UPDATE"] == "true"
            },
            "installer": {
                "source": installer_source,
                "final_url": final_url,
                "content_type": content_type,
                "size": len(installer_data),
                "sha256": installer_sha256,
                "bash_syntax": command_metadata(syntax),
                "help": command_metadata(installer_help),
                "supported_options": options,
                "selected_strategy": strategy,
            },
            "home_unchanged_after_help": True,
            "profiles": {
                "before": before_profiles,
                "after_help": after_help_profiles,
                "after_first": after_first_profiles,
                "after_second": after_second_profiles,
                "unchanged_after_help": True,
                "unchanged_after_first": before_profiles == after_first_profiles,
                "unchanged_after_second": before_profiles == after_second_profiles,
            },
            "filesystem": {
                "before": before,
                "after_first": after_first,
                "after_second": after_second,
            },
            "first_install": install_result(first_install_process),
            "second_install": install_result(second_install_process),
            "binary_after_first": binary_after_first,
            "binary_after_second": binary_after_second,
            "expected_binary_present": binary.is_file(),
            "binary_stable_across_second_install": (
                binary_after_first is not None
                and binary_after_second is not None
                and binary_after_first["sha256"] == binary_after_second["sha256"]
            ),
            "installed_legal_files": legal_files(home),
        }


def validate_report(report: dict[str, Any]) -> list[str]:
    """Return every blocking inspection finding."""
    errors: list[str] = []
    installer = report["installer"]
    if installer["help"]["exit_code"] != 0:
        errors.append("installer --help failed")
    if not report["home_unchanged_after_help"]:
        errors.append("installer --help changed the isolated home")
    if not report["profiles"]["unchanged_after_help"]:
        errors.append("installer --help changed a shell profile")
    if installer["selected_strategy"] not in {
        "custom-directory",
        "skip-shell-modification-flags",
    }:
        errors.append("no reviewed installation strategy was selected")
    if report["first_install"]["exit_code"] != 0:
        errors.append("first installer execution failed")
    if report["second_install"]["exit_code"] != 0:
        errors.append("second installer execution failed")
    if not report["expected_binary_present"]:
        errors.append(f"expected executable was not installed at ~/{EXPECTED_BINARY}")
    for stage in ("after_first", "after_second"):
        if not report["profiles"][f"unchanged_{stage}"]:
            errors.append(f"shell profiles changed {stage.replace('_', ' ')}")
    binary = report["binary_after_second"]
    if not isinstance(binary, dict):
        errors.append("installed executable could not be inspected")
        return errors
    if binary["version"]["exit_code"] != 0:
        errors.append("installed executable --version failed")
    if binary["version"]["reported_version"] is None:
        errors.append("installed executable reported no unambiguous version")
    if binary["help"]["exit_code"] != 0:
        errors.append("installed executable --help failed")
    if not binary["format"]["elf_64_bit"] or not binary["format"]["x86_64"]:
        errors.append("installed executable is not the expected Linux AMD64 format")
    if binary["dynamic_libraries"]["unrecognized_count"] != 0:
        errors.append("installed executable introduced unreviewed dynamic libraries")
    if report["expected_binary_present"] and not report["binary_stable_across_second_install"]:
        errors.append("repeated installer run changed the executable unexpectedly")
    if not report["environment_controls"]["auto_update_disabled"]:
        errors.append("inspection did not disable background auto-update")
    return errors


def parse_sha256(value: str) -> str:
    """Validate a lowercase or uppercase hexadecimal SHA-256 value."""
    normalized = value.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise argparse.ArgumentTypeError("expected a 64-character SHA-256 value")
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse official-inspection and local-fixture arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-installer-sha256", type=parse_sha256)
    parser.add_argument("--expected-binary-sha256", type=parse_sha256)
    parser.add_argument(
        "--installer-fixture",
        type=Path,
        help="Local test fixture only; official mode requires approved digests",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Write normalized evidence and fail on blocking findings."""
    args = parse_args(argv)
    try:
        report = inspect(
            args.installer_fixture,
            args.expected_installer_sha256,
            args.expected_binary_sha256,
        )
        errors = validate_report(report)
    except (OSError, RuntimeError) as error:
        print(f"Antigravity inspection rejected before evidence generation: {error}", file=sys.stderr)
        return 1

    report["blocking_findings"] = errors
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if errors:
        print(f"Antigravity inspection found {len(errors)} blocking issue(s).", file=sys.stderr)
        return 1
    print("Antigravity inspection: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
