#!/usr/bin/env python3
"""Discover an Antigravity payload hash after explicit installer-hash admission.

This stage may execute the explicitly admitted installer, but it never invokes the
installed `agy` payload. The discovered payload hash is metadata for a separate
human admission step before full binary inspection.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
INSPECTOR_PATH = ROOT / "inspect-antigravity-cli.py"
SPEC = importlib.util.spec_from_file_location("antigravity_inspector", INSPECTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load inspect-antigravity-cli.py")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)

MAX_PAYLOAD_SIZE = 512 * 1024 * 1024


class DiscoveryError(ValueError):
    """Raised when the admitted installer does not produce bounded payload metadata."""


def discover(
    *,
    expected_installer_sha256: str,
    installer_fixture: Path | None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="antigravity-payload-discovery-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        installer = root / "install.sh"
        fixture = installer_fixture is not None
        if fixture:
            data, content_type, final_url = INSPECTOR.load_local_installer(
                installer_fixture, installer
            )
            source = final_url
        else:
            data, content_type, final_url = INSPECTOR.download_installer(installer)
            source = INSPECTOR.OFFICIAL_INSTALLER_URL

        installer_sha256 = INSPECTOR.verify_installer_before_execution(
            data,
            expected_sha256=expected_installer_sha256,
            final_url=final_url,
            fixture=fixture,
        )
        installer.chmod(0o700)
        env = INSPECTOR.inspection_environment(home)
        before_profiles = INSPECTOR.profile_snapshot(home)
        before = INSPECTOR.snapshot(home)

        syntax = INSPECTOR.run(["/bin/bash", "-n", str(installer)], env=env, cwd=root)
        if syntax.returncode != 0:
            raise DiscoveryError("admitted installer is not valid Bash")
        help_result = INSPECTOR.run(
            ["/bin/bash", str(installer), "--help"], env=env, cwd=root, timeout=30
        )
        if help_result.returncode != 0:
            raise DiscoveryError("admitted installer --help failed")
        options = INSPECTOR.installer_options(help_result)
        if INSPECTOR.snapshot(home) != before or INSPECTOR.profile_snapshot(home) != before_profiles:
            raise DiscoveryError("admitted installer --help changed the isolated home")
        strategy, install_command = INSPECTOR.choose_install_command(installer, options, home)
        install_process = INSPECTOR.run(install_command, env=env, cwd=root, timeout=300)
        if install_process.returncode != 0:
            raise DiscoveryError("admitted installer execution failed")

        binary = home / INSPECTOR.EXPECTED_BINARY
        if not binary.is_file() or binary.is_symlink():
            raise DiscoveryError("admitted installer did not produce the expected regular payload")
        payload_size = binary.stat().st_size
        if not 0 < payload_size <= MAX_PAYLOAD_SIZE:
            raise DiscoveryError("discovered payload size is outside the supported boundary")
        payload_sha256 = INSPECTOR.sha256_file(binary)
        after_profiles = INSPECTOR.profile_snapshot(home)
        profiles_unchanged = before_profiles == after_profiles
        if not profiles_unchanged:
            raise DiscoveryError("admitted installer changed a shell profile")

        return {
            "schema_version": 1,
            "kind": "antigravity-payload-discovery",
            "installer": {
                "source": source,
                "final_url": final_url,
                "content_type": content_type,
                "size": len(data),
                "sha256": installer_sha256,
                "bash_syntax": INSPECTOR.command_metadata(syntax),
                "help": INSPECTOR.command_metadata(help_result),
                "supported_options": options,
                "selected_strategy": strategy,
            },
            "installation": INSPECTOR.install_result(install_process),
            "payload": {
                "path": INSPECTOR.EXPECTED_BINARY.as_posix(),
                "size": payload_size,
                "sha256": payload_sha256,
            },
            "profiles_unchanged": profiles_unchanged,
            "blocking_findings": [],
        }


def validate_report(report: dict[str, Any], *, expected_installer_sha256: str | None = None) -> None:
    if set(report) != {
        "schema_version",
        "kind",
        "installer",
        "installation",
        "payload",
        "profiles_unchanged",
        "blocking_findings",
    }:
        raise DiscoveryError("payload discovery report has unexpected top-level fields")
    if report["schema_version"] != 1 or report["kind"] != "antigravity-payload-discovery":
        raise DiscoveryError("payload discovery report has an unsupported schema")
    if report["blocking_findings"] != [] or report["profiles_unchanged"] is not True:
        raise DiscoveryError("payload discovery report contains a blocking finding")
    installer = report["installer"]
    payload = report["payload"]
    if not isinstance(installer, dict) or not isinstance(payload, dict):
        raise DiscoveryError("payload discovery metadata is malformed")
    installer_sha = installer.get("sha256")
    payload_sha = payload.get("sha256")
    if not isinstance(installer_sha, str) or not INSPECTOR.parse_sha256(installer_sha):
        raise DiscoveryError("payload discovery installer SHA-256 is invalid")
    if expected_installer_sha256 is not None and installer_sha != expected_installer_sha256:
        raise DiscoveryError("payload discovery installer SHA-256 differs from the admitted value")
    if not isinstance(payload_sha, str) or not INSPECTOR.parse_sha256(payload_sha):
        raise DiscoveryError("payload discovery binary SHA-256 is invalid")
    if payload.get("path") != INSPECTOR.EXPECTED_BINARY.as_posix():
        raise DiscoveryError("payload discovery path is unexpected")
    payload_size = payload.get("size")
    if not isinstance(payload_size, int) or not 0 < payload_size <= MAX_PAYLOAD_SIZE:
        raise DiscoveryError("payload discovery size is invalid")
    installation = report["installation"]
    if not isinstance(installation, dict) or installation.get("exit_code") != 0:
        raise DiscoveryError("payload discovery installer did not succeed")


def write_report(
    output: Path,
    *,
    expected_installer_sha256: str,
    installer_fixture: Path | None,
) -> dict[str, Any]:
    report = discover(
        expected_installer_sha256=expected_installer_sha256,
        installer_fixture=installer_fixture,
    )
    validate_report(report, expected_installer_sha256=expected_installer_sha256)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-installer-sha256", type=INSPECTOR.parse_sha256, required=True
    )
    parser.add_argument("--installer-fixture", type=Path)
    args = parser.parse_args()
    try:
        write_report(
            args.output,
            expected_installer_sha256=args.expected_installer_sha256,
            installer_fixture=args.installer_fixture,
        )
    except (OSError, RuntimeError, DiscoveryError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print("Antigravity payload discovery: OK (payload not executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
