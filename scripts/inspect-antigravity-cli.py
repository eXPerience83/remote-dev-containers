#!/usr/bin/env python3
"""Inspect the official Antigravity CLI installer in an ephemeral home directory.

The script records only metadata, hashes, paths and bounded command output. It
never copies the installer or installed Antigravity binary into the repository
or generated report.
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
URL_RE = re.compile(r"https://[^\s'\"<>]+")


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def file_record(path: Path, root: Path) -> dict[str, Any]:
    """Return bounded metadata for one filesystem object without its contents."""
    relative = path.relative_to(root).as_posix()
    metadata = path.lstat()
    record: dict[str, Any] = {
        "path": relative,
        "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
    }
    if path.is_symlink():
        record["type"] = "symlink"
        record["target"] = os.readlink(path)
    elif path.is_dir():
        record["type"] = "directory"
    elif path.is_file():
        data = path.read_bytes()
        record.update(
            {
                "type": "file",
                "size": len(data),
                "sha256": sha256_bytes(data),
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
    """Fingerprint shell profiles that the installer must not modify."""
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
    """Run a bounded command without a shell and capture textual output."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return subprocess.CompletedProcess(command, 124, stdout, stderr + "\nTIMEOUT")


def bounded_lines(text: str, limit: int = 40) -> list[str]:
    """Return a small printable excerpt suitable for review evidence."""
    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lines.append(line[:500])
        if len(lines) >= limit:
            break
    return lines


def download_installer(destination: Path) -> tuple[bytes, str | None, str]:
    """Download the installer from the fixed official HTTPS endpoint."""
    request = urllib.request.Request(
        OFFICIAL_INSTALLER_URL,
        headers={"User-Agent": "remote-dev-containers-antigravity-inspection"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            final_url = response.geturl()
            if not final_url.startswith("https://"):
                raise RuntimeError(f"installer redirected to a non-HTTPS URL: {final_url}")
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


def command_metadata(completed: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Convert process output into bounded non-secret review metadata."""
    return {
        "exit_code": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout.encode()),
        "stderr_sha256": sha256_bytes(completed.stderr.encode()),
        "stdout_lines": bounded_lines(completed.stdout),
        "stderr_lines": bounded_lines(completed.stderr),
    }


def tool_output(command: list[str], env: dict[str, str], cwd: Path) -> dict[str, Any]:
    """Run an optional local inspection utility and return bounded output."""
    executable = shutil.which(command[0], path=env["PATH"])
    if executable is None:
        return {"available": False}
    completed = run([executable, *command[1:]], env=env, cwd=cwd)
    return {"available": True, **command_metadata(completed)}


def inspect_binary(binary: Path, env: dict[str, str], cwd: Path) -> dict[str, Any]:
    """Inspect the installed executable without starting authentication."""
    data = binary.read_bytes()
    version = run([str(binary), "--version"], env=env, cwd=cwd, timeout=30)
    help_result = run([str(binary), "--help"], env=env, cwd=cwd, timeout=30)
    return {
        "path": str(binary),
        "size": len(data),
        "sha256": sha256_bytes(data),
        "version": command_metadata(version),
        "help": command_metadata(help_result),
        "file": tool_output(["file", "-b", str(binary)], env, cwd),
        "readelf_header": tool_output(["readelf", "-h", str(binary)], env, cwd),
        "dynamic_dependencies": tool_output(["ldd", str(binary)], env, cwd),
    }


def legal_files(home: Path) -> list[dict[str, Any]]:
    """List license-like files installed under the isolated home directory."""
    records = []
    for path in home.rglob("*"):
        if path.is_file() and LEGAL_NAME_RE.fullmatch(path.name):
            records.append(file_record(path, home))
    return sorted(records, key=lambda item: item["path"])


def referenced_hosts(installer_text: str) -> list[str]:
    """Return unique HTTPS hostnames visibly embedded in the installer text."""
    hosts: set[str] = set()
    for url in URL_RE.findall(installer_text):
        match = re.match(r"https://([^/:?#]+)", url)
        if match:
            hosts.add(match.group(1).lower())
    return sorted(hosts)


def inspection_environment(home: Path) -> dict[str, str]:
    """Construct a minimal environment that contains no repository credentials."""
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
        "CI": "1",
    }


def choose_install_command(
    installer: Path,
    installer_help: subprocess.CompletedProcess[str],
    home: Path,
) -> tuple[str, list[str], dict[str, bool]]:
    """Choose only a vendor-advertised installation strategy."""
    help_text = f"{installer_help.stdout}\n{installer_help.stderr}"
    supported = {
        "custom_directory": "--dir" in help_text,
        "skip_aliases": "--skip-aliases" in help_text,
        "skip_path": "--skip-path" in help_text,
    }
    base = ["/bin/bash", str(installer)]
    if supported["custom_directory"]:
        return (
            "custom-directory",
            [*base, "--dir", str(home / EXPECTED_BINARY.parent)],
            supported,
        )
    if supported["skip_aliases"] and supported["skip_path"]:
        return (
            "skip-shell-modification-flags",
            [*base, "--skip-aliases", "--skip-path"],
            supported,
        )
    raise RuntimeError(
        "installer help exposes neither --dir nor the documented pair "
        "--skip-aliases/--skip-path"
    )


def inspect(installer_fixture: Path | None) -> dict[str, Any]:
    """Perform one complete installation and idempotent-update inspection."""
    with tempfile.TemporaryDirectory(prefix="antigravity-inspection-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        installer = root / "install.sh"
        if installer_fixture is None:
            installer_data, content_type, final_url = download_installer(installer)
            installer_source = OFFICIAL_INSTALLER_URL
        else:
            installer_data, content_type, final_url = load_local_installer(
                installer_fixture, installer
            )
            installer_source = final_url
        installer.chmod(0o700)

        installer_text = installer_data.decode("utf-8", errors="replace")
        env = inspection_environment(home)
        syntax = run(["/bin/bash", "-n", str(installer)], env=env, cwd=root)
        if syntax.returncode != 0:
            raise RuntimeError(f"installer is not valid Bash: {syntax.stderr}")

        installer_help = run(
            ["/bin/bash", str(installer), "--help"], env=env, cwd=root, timeout=30
        )
        if installer_help.returncode != 0:
            raise RuntimeError("installer --help failed")
        strategy, install_command, supported_options = choose_install_command(
            installer, installer_help, home
        )

        before_profiles = profile_snapshot(home)
        before = snapshot(home)
        first_install = run(install_command, env=env, cwd=root, timeout=300)
        after_first = snapshot(home)
        after_first_profiles = profile_snapshot(home)

        binary = home / EXPECTED_BINARY
        binary_after_first = inspect_binary(binary, env, root) if binary.is_file() else None

        second_install = run(install_command, env=env, cwd=root, timeout=300)
        after_second = snapshot(home)
        after_second_profiles = profile_snapshot(home)
        binary_after_second = inspect_binary(binary, env, root) if binary.is_file() else None

        return {
            "schema_version": 1,
            "inspected_at_utc": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
            "platform": {
                "system": platform.system(),
                "machine": platform.machine(),
                "release": platform.release(),
            },
            "installer": {
                "source": installer_source,
                "final_url": final_url,
                "content_type": content_type,
                "size": len(installer_data),
                "sha256": sha256_bytes(installer_data),
                "bash_syntax": command_metadata(syntax),
                "help": command_metadata(installer_help),
                "supported_options": supported_options,
                "selected_strategy": strategy,
                "selected_arguments": install_command[2:],
                "text_mentions_skip_aliases": "--skip-aliases" in installer_text,
                "text_mentions_skip_path": "--skip-path" in installer_text,
                "text_mentions_custom_directory": "--dir" in installer_text,
                "referenced_https_hosts": referenced_hosts(installer_text),
            },
            "first_install": command_metadata(first_install),
            "second_install": command_metadata(second_install),
            "profiles": {
                "before": before_profiles,
                "after_first": after_first_profiles,
                "after_second": after_second_profiles,
                "unchanged_after_first": before_profiles == after_first_profiles,
                "unchanged_after_second": before_profiles == after_second_profiles,
            },
            "filesystem": {
                "before": before,
                "after_first": after_first,
                "after_second": after_second,
            },
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


def validate_report(report: dict[str, Any], *, fixture: bool) -> list[str]:
    """Return blocking inspection findings that prevent implementation."""
    errors: list[str] = []
    installer = report["installer"]
    if not fixture and installer["source"] != OFFICIAL_INSTALLER_URL:
        errors.append("inspection did not use the fixed official installer URL")
    if not fixture and not str(installer["final_url"]).startswith("https://"):
        errors.append("official installer resolved to a non-HTTPS URL")
    if installer["help"]["exit_code"] != 0:
        errors.append("installer --help failed")
    if installer["selected_strategy"] not in {
        "custom-directory",
        "skip-shell-modification-flags",
    }:
        errors.append("no supported safe installation strategy was selected")
    if report["first_install"]["exit_code"] != 0:
        errors.append("first installer execution failed")
    if report["second_install"]["exit_code"] != 0:
        errors.append("second installer execution failed")
    if not report["expected_binary_present"]:
        errors.append(f"expected executable was not installed at ~/{EXPECTED_BINARY}")
    if not report["profiles"]["unchanged_after_first"]:
        errors.append("shell profiles changed during first installation")
    if not report["profiles"]["unchanged_after_second"]:
        errors.append("shell profiles changed during the second installer run")
    binary = report["binary_after_second"]
    if isinstance(binary, dict) and binary["version"]["exit_code"] != 0:
        errors.append("installed executable does not support a successful --version check")
    return errors


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse inspection and local-fixture arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--installer-fixture",
        type=Path,
        help="Local test fixture only; production inspection always uses the official URL",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the inspection, write JSON evidence and fail on blocking findings."""
    args = parse_args(argv)
    try:
        report = inspect(args.installer_fixture)
        errors = validate_report(report, fixture=args.installer_fixture is not None)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    report["blocking_findings"] = errors
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
