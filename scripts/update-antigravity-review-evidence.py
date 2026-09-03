#!/usr/bin/env python3
"""Promote a fully hash-admitted live inspection into reviewed JSON evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")


class EvidenceError(ValueError):
    """Raised when candidate evidence cannot safely replace reviewed metadata."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"could not read valid JSON from {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{path} must contain one JSON object")
    return value


def exact_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise EvidenceError(f"{label} is not a normalized SHA-256 value")
    return value


def explicit_paths(snapshot: object) -> list[str]:
    if not isinstance(snapshot, list):
        raise EvidenceError("inspection filesystem snapshot is malformed")
    paths: list[str] = []
    for record in snapshot:
        if not isinstance(record, dict) or record.get("path_redacted") is not False:
            raise EvidenceError("inspection contains an unexpected redacted filesystem path")
        path = record.get("path")
        if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
            raise EvidenceError("inspection contains an unsafe filesystem path")
        paths.append(path)
    return sorted(set(paths))


def validate_detection(detection: dict[str, Any]) -> dict[str, Any]:
    if detection.get("schema_version") != 1 or detection.get("kind") != "antigravity-installer-detection":
        raise EvidenceError("Antigravity detection schema is unsupported")
    if detection.get("changed") is not True:
        raise EvidenceError("Antigravity detection does not describe a changed installer")
    installer = detection.get("installer")
    if not isinstance(installer, dict):
        raise EvidenceError("Antigravity detection installer metadata is malformed")
    exact_sha(installer.get("sha256"), "detected installer SHA-256")
    hosts = installer.get("referenced_https_hosts")
    if not isinstance(hosts, list) or hosts != sorted(set(hosts)):
        raise EvidenceError("Antigravity detection host metadata is not normalized")
    if any(not isinstance(host, str) or len(host) > 253 for host in hosts):
        raise EvidenceError("Antigravity detection host metadata is invalid")
    return installer


def validate_live(live: dict[str, Any], detection_installer: dict[str, Any]) -> dict[str, Any]:
    if live.get("schema_version") != 2 or live.get("blocking_findings") != []:
        raise EvidenceError("full Antigravity inspection did not pass schema-2 validation")
    installer = live.get("installer")
    binary = live.get("binary_after_second")
    if not isinstance(installer, dict) or not isinstance(binary, dict):
        raise EvidenceError("full Antigravity inspection is missing installer/binary metadata")
    installer_sha = exact_sha(installer.get("sha256"), "inspected installer SHA-256")
    if installer_sha != detection_installer.get("sha256"):
        raise EvidenceError("full inspection installer differs from the detected candidate")
    if installer.get("final_url") != detection_installer.get("final_url"):
        raise EvidenceError("full inspection final URL differs from the detected candidate")
    exact_sha(binary.get("sha256"), "inspected payload SHA-256")
    version = binary.get("version")
    if not isinstance(version, dict) or version.get("exit_code") != 0:
        raise EvidenceError("inspected payload version check did not succeed")
    reported_version = version.get("reported_version")
    if not isinstance(reported_version, str) or not _SAFE_VERSION_RE.fullmatch(reported_version):
        raise EvidenceError("inspected payload reported an unsafe or ambiguous version")
    if live.get("expected_binary_present") is not True or live.get("binary_stable_across_second_install") is not True:
        raise EvidenceError("inspected payload was not stable across the reviewed repeat-install contract")
    profiles = live.get("profiles")
    if not isinstance(profiles, dict) or profiles.get("unchanged_after_second") is not True:
        raise EvidenceError("full inspection changed a shell profile")
    controls = live.get("environment_controls")
    if not isinstance(controls, dict) or controls.get("auto_update_disabled") is not True:
        raise EvidenceError("full inspection did not keep vendor auto-update disabled")
    return binary


def build_reviewed(
    *,
    live: dict[str, Any],
    detection: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    if current.get("schema_version") != 2:
        raise EvidenceError("current reviewed Antigravity evidence has an unsupported schema")
    for preserved in ("workflow", "official_runtime_controls", "legal_and_distribution"):
        if not isinstance(current.get(preserved), dict):
            raise EvidenceError(f"current reviewed evidence is missing preserved {preserved} policy")

    detected_installer = validate_detection(detection)
    binary = validate_live(live, detected_installer)
    installer = live["installer"]
    first_install = live.get("first_install")
    second_install = live.get("second_install")
    if not isinstance(first_install, dict) or not isinstance(second_install, dict):
        raise EvidenceError("full inspection installation metadata is malformed")
    if first_install.get("exit_code") != 0 or second_install.get("exit_code") != 0:
        raise EvidenceError("full inspection installer execution did not succeed")

    inspected_at = live.get("inspected_at_utc")
    if not isinstance(inspected_at, str) or len(inspected_at) < 10:
        raise EvidenceError("full inspection timestamp is invalid")
    inspection_date = inspected_at[:10]

    binary_format = binary.get("format")
    libraries = binary.get("dynamic_libraries")
    help_result = binary.get("help")
    if not isinstance(binary_format, dict) or not isinstance(libraries, dict) or not isinstance(help_result, dict):
        raise EvidenceError("full inspection binary metadata is malformed")
    if libraries.get("unrecognized_count") != 0:
        raise EvidenceError("full inspection introduced unreviewed dynamic libraries")
    recognized = libraries.get("recognized")
    if not isinstance(recognized, list) or any(not isinstance(item, str) for item in recognized):
        raise EvidenceError("full inspection dynamic-library metadata is malformed")

    legal_records = live.get("installed_legal_files")
    if not isinstance(legal_records, list):
        raise EvidenceError("full inspection legal-file metadata is malformed")
    legal_paths: list[str] = []
    for record in legal_records:
        if not isinstance(record, dict) or record.get("path_redacted") is not False:
            raise EvidenceError("full inspection contains an unexpected legal-file path")
        path = record.get("path")
        if not isinstance(path, str):
            raise EvidenceError("full inspection legal-file path is malformed")
        legal_paths.append(path)

    return {
        "schema_version": 2,
        "inspection_date_utc": inspection_date,
        "workflow": current["workflow"],
        "installer": {
            "official_url": current.get("installer", {}).get(
                "official_url", "https://antigravity.google/cli/install.sh"
            ),
            "final_url": installer.get("final_url"),
            "content_type": installer.get("content_type"),
            "size": installer.get("size"),
            "sha256": installer.get("sha256"),
            "advertised_options": installer.get("supported_options"),
            "selected_strategy": installer.get("selected_strategy"),
            "referenced_https_hosts": detected_installer.get("referenced_https_hosts", []),
        },
        "installed_binary": {
            "relative_path": binary.get("path"),
            "version": binary["version"]["reported_version"],
            "size": binary.get("size"),
            "sha256": binary.get("sha256"),
            "format": binary_format,
            "dynamic_dependencies": recognized,
            "version_check_exit_code": binary["version"].get("exit_code"),
            "help_check_exit_code": help_result.get("exit_code"),
        },
        "filesystem": {
            "created_relative_paths": explicit_paths(live.get("filesystem", {}).get("after_second")),
            "shell_profiles_changed": False,
            "installed_license_or_notice_files": sorted(set(legal_paths)),
        },
        "repeat_install": {
            "exit_code": second_install.get("exit_code"),
            "binary_hash_unchanged": live.get("binary_stable_across_second_install"),
            "behavior": (
                "The installer detected the existing binary and a repeated reviewed run "
                "did not replace the admitted executable."
            ),
        },
        "official_runtime_controls": current["official_runtime_controls"],
        "legal_and_distribution": current["legal_and_distribution"],
        "blocking_findings": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--detection", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        reviewed = build_reviewed(
            live=load_json(args.live),
            detection=load_json(args.detection),
            current=load_json(args.current),
        )
        args.output.write_text(
            json.dumps(reviewed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except (OSError, EvidenceError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print("Antigravity reviewed evidence update: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
