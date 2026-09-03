#!/usr/bin/env python3
"""Reconcile live Antigravity detection with optional proposed review state."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DISCOVERY_PATH = ROOT / "discover-antigravity-payload.py"
DISCOVERY_SPEC = importlib.util.spec_from_file_location(
    "antigravity_payload_discovery", DISCOVERY_PATH
)
if DISCOVERY_SPEC is None or DISCOVERY_SPEC.loader is None:
    raise RuntimeError("could not load discover-antigravity-payload.py")
DISCOVERY = importlib.util.module_from_spec(DISCOVERY_SPEC)
DISCOVERY_SPEC.loader.exec_module(DISCOVERY)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
_CONTENT_TYPE_RE = re.compile(r"^[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+$")
_LIBRARY_RE = re.compile(r"^lib[A-Za-z0-9_.+-]*\.so(?:\.[0-9]+)*$")
_INTERPRETER_RE = re.compile(r"^/[A-Za-z0-9._+/-]{1,199}$")
OFFICIAL_URL = "https://antigravity.google/cli/install.sh"
OFFICIAL_HOST = "antigravity.google"
EXPECTED_BINARY = ".local/bin/agy"
MAX_JSON_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = DISCOVERY.MAX_PAYLOAD_SIZE
KNOWN_SYSTEM_LIBRARIES = {
    "libc.so.6",
    "libdl.so.2",
    "libm.so.6",
    "libpthread.so.0",
    "libresolv.so.2",
    "librt.so.1",
}
_EXPECTED_INSTALLER_KEYS = {
    "official_url",
    "final_url",
    "content_type",
    "size",
    "sha256",
    "advertised_options",
    "selected_strategy",
    "referenced_https_hosts",
}
_EXPECTED_OPTION_KEYS = {"custom_directory", "skip_aliases", "skip_path"}
_EXPECTED_BINARY_KEYS = {
    "relative_path",
    "version",
    "size",
    "sha256",
    "format",
    "dynamic_dependencies",
    "version_check_exit_code",
    "help_check_exit_code",
}
_EXPECTED_FORMAT_KEYS = {
    "elf_64_bit",
    "x86_64",
    "pie",
    "dynamically_linked",
    "stripped",
    "interpreter",
}
_EXPECTED_FILESYSTEM_KEYS = {
    "created_relative_paths",
    "shell_profiles_changed",
    "installed_license_or_notice_files",
}
_EXPECTED_REPEAT_KEYS = {"exit_code", "binary_hash_unchanged", "behavior"}


class ReconcileError(ValueError):
    """Raised when persisted automation state violates the reviewed schema boundary."""


def load_json(path: Path) -> dict[str, Any]:
    """Load one bounded UTF-8 JSON object."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReconcileError(f"could not read {path}") from exc
    if len(raw) > MAX_JSON_BYTES:
        raise ReconcileError(f"{path} exceeds the metadata-only size boundary")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReconcileError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ReconcileError(f"{path} must contain one JSON object")
    return value


def sha256(value: object, label: str) -> str:
    """Require a normalized lowercase SHA-256."""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReconcileError(f"{label} is invalid")
    return value


def safe_official_url(value: object) -> bool:
    """Return whether a URL remains on the reviewed official HTTPS origin."""
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == OFFICIAL_HOST
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and parsed.fragment == ""
    )


def _require_exact_keys(value: object, expected: set[str], label: str) -> dict[str, Any]:
    """Require one dictionary to match a fixed reviewed schema exactly."""
    if not isinstance(value, dict) or set(value) != expected:
        raise ReconcileError(f"{label} has an unsupported schema")
    return value


def _require_positive_int(value: object, maximum: int, label: str) -> int:
    """Require a non-boolean positive integer within a fixed bound."""
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ReconcileError(f"{label} is outside the supported boundary")
    return value


def _require_normalized_strings(
    value: object,
    *,
    label: str,
    maximum_items: int,
    maximum_length: int,
) -> list[str]:
    """Require a small sorted unique list of printable strings."""
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ReconcileError(f"{label} is malformed")
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > maximum_length
        or not item.isprintable()
        for item in value
    ):
        raise ReconcileError(f"{label} contains an invalid value")
    if value != sorted(set(value)):
        raise ReconcileError(f"{label} is not normalized")
    return value


def _safe_relative_path(value: str) -> bool:
    """Return whether a persisted filesystem path is explicit and relative."""
    path = Path(value)
    return (
        bool(value)
        and len(value) <= 300
        and value.isprintable()
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def validate_detection(value: dict[str, Any]) -> dict[str, Any]:
    """Validate installer detection metadata."""
    if set(value) != {
        "schema_version",
        "kind",
        "installer",
        "reviewed_installer_sha256",
        "changed",
    }:
        raise ReconcileError("live detection contains unexpected fields")
    if value.get("schema_version") != 1 or value.get("kind") != "antigravity-installer-detection":
        raise ReconcileError("live detection schema is unsupported")
    installer = value.get("installer")
    if not isinstance(installer, dict):
        raise ReconcileError("live detection installer metadata is malformed")
    sha256(installer.get("sha256"), "live installer SHA-256")
    if installer.get("source") != OFFICIAL_URL or not safe_official_url(installer.get("final_url")):
        raise ReconcileError("live detector left the reviewed official HTTPS origin")
    if not isinstance(installer.get("size"), int) or not 0 < installer["size"] <= 2 * 1024 * 1024:
        raise ReconcileError("live installer size is outside the supported boundary")
    hosts = installer.get("referenced_https_hosts")
    if not isinstance(hosts, list) or hosts != sorted(set(hosts)):
        raise ReconcileError("live installer host metadata is not normalized")
    if any(not isinstance(host, str) or not host or len(host) > 253 for host in hosts):
        raise ReconcileError("live installer host metadata is invalid")
    reviewed_sha = sha256(value.get("reviewed_installer_sha256"), "reviewed installer SHA-256")
    if value.get("changed") is not (installer["sha256"] != reviewed_sha):
        raise ReconcileError("live detection changed flag is inconsistent")
    return installer


def validate_reviewed(
    value: dict[str, Any], *, baseline: dict[str, Any]
) -> tuple[str, str]:
    """Validate complete reviewed evidence while preserving human-owned policy fields."""
    expected_top = {
        "schema_version",
        "inspection_date_utc",
        "workflow",
        "installer",
        "installed_binary",
        "filesystem",
        "repeat_install",
        "official_runtime_controls",
        "legal_and_distribution",
        "blocking_findings",
    }
    if set(value) != expected_top or value.get("schema_version") != 2:
        raise ReconcileError("proposed reviewed evidence has an unsupported schema")
    if value.get("blocking_findings") != []:
        raise ReconcileError("proposed reviewed evidence contains blocking findings")

    inspection_date = value.get("inspection_date_utc")
    if not isinstance(inspection_date, str):
        raise ReconcileError("proposed reviewed evidence has an invalid inspection date")
    try:
        parsed_date = dt.date.fromisoformat(inspection_date)
    except ValueError as exc:
        raise ReconcileError("proposed reviewed evidence has an invalid inspection date") from exc
    if parsed_date.isoformat() != inspection_date:
        raise ReconcileError("proposed reviewed evidence has a non-normalized inspection date")

    for preserved in ("workflow", "official_runtime_controls", "legal_and_distribution"):
        if not isinstance(value.get(preserved), dict) or not isinstance(baseline.get(preserved), dict):
            raise ReconcileError(f"proposed reviewed evidence is missing human-owned {preserved}")
        if value.get(preserved) != baseline.get(preserved):
            raise ReconcileError(f"proposed reviewed evidence changed human-owned {preserved}")

    installer = _require_exact_keys(
        value.get("installer"), _EXPECTED_INSTALLER_KEYS, "proposed installer metadata"
    )
    if installer.get("official_url") != OFFICIAL_URL or installer.get("final_url") != OFFICIAL_URL:
        raise ReconcileError("proposed reviewed evidence changed the fixed installer origin")
    content_type = installer.get("content_type")
    if not isinstance(content_type, str) or not _CONTENT_TYPE_RE.fullmatch(content_type):
        raise ReconcileError("proposed installer content type is invalid")
    _require_positive_int(installer.get("size"), 2 * 1024 * 1024, "proposed installer size")
    installer_sha = sha256(installer.get("sha256"), "proposed installer SHA-256")
    options = _require_exact_keys(
        installer.get("advertised_options"),
        _EXPECTED_OPTION_KEYS,
        "proposed installer option metadata",
    )
    if any(not isinstance(options[key], bool) for key in _EXPECTED_OPTION_KEYS):
        raise ReconcileError("proposed installer option metadata is malformed")
    strategy = installer.get("selected_strategy")
    if strategy not in {"custom-directory", "skip-shell-modification-flags"}:
        raise ReconcileError("proposed installer strategy is unsupported")
    if strategy == "custom-directory" and options["custom_directory"] is not True:
        raise ReconcileError("proposed installer strategy is inconsistent with advertised options")
    if strategy == "skip-shell-modification-flags" and not (
        options["skip_aliases"] is True and options["skip_path"] is True
    ):
        raise ReconcileError("proposed installer strategy is inconsistent with advertised options")
    _require_normalized_strings(
        installer.get("referenced_https_hosts"),
        label="proposed installer host metadata",
        maximum_items=32,
        maximum_length=253,
    )

    binary = _require_exact_keys(
        value.get("installed_binary"), _EXPECTED_BINARY_KEYS, "proposed binary metadata"
    )
    if binary.get("relative_path") != EXPECTED_BINARY:
        raise ReconcileError("proposed reviewed evidence changed the expected binary path")
    version = binary.get("version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ReconcileError("proposed reviewed evidence has an invalid binary version")
    _require_positive_int(binary.get("size"), MAX_PAYLOAD_BYTES, "proposed binary size")
    payload_sha = sha256(binary.get("sha256"), "proposed binary SHA-256")

    binary_format = _require_exact_keys(
        binary.get("format"), _EXPECTED_FORMAT_KEYS, "proposed binary format metadata"
    )
    for key in _EXPECTED_FORMAT_KEYS - {"interpreter"}:
        if not isinstance(binary_format[key], bool):
            raise ReconcileError("proposed binary format metadata is malformed")
    if binary_format["elf_64_bit"] is not True or binary_format["x86_64"] is not True:
        raise ReconcileError("proposed binary is not the reviewed Linux AMD64 format")
    interpreter = binary_format.get("interpreter")
    if interpreter is not None and (
        not isinstance(interpreter, str) or not _INTERPRETER_RE.fullmatch(interpreter)
    ):
        raise ReconcileError("proposed binary interpreter metadata is invalid")

    libraries = _require_normalized_strings(
        binary.get("dynamic_dependencies"),
        label="proposed binary dependency metadata",
        maximum_items=32,
        maximum_length=128,
    )
    if any(not _LIBRARY_RE.fullmatch(item) or item not in KNOWN_SYSTEM_LIBRARIES for item in libraries):
        raise ReconcileError("proposed binary dependency metadata contains an unreviewed library")
    if binary.get("version_check_exit_code") != 0 or binary.get("help_check_exit_code") != 0:
        raise ReconcileError("proposed binary command validation did not succeed")

    filesystem = _require_exact_keys(
        value.get("filesystem"), _EXPECTED_FILESYSTEM_KEYS, "proposed filesystem metadata"
    )
    created_paths = _require_normalized_strings(
        filesystem.get("created_relative_paths"),
        label="proposed created-path metadata",
        maximum_items=1000,
        maximum_length=300,
    )
    legal_paths = _require_normalized_strings(
        filesystem.get("installed_license_or_notice_files"),
        label="proposed legal-file metadata",
        maximum_items=100,
        maximum_length=300,
    )
    if any(not _safe_relative_path(path) for path in [*created_paths, *legal_paths]):
        raise ReconcileError("proposed filesystem metadata contains an unsafe path")
    if filesystem.get("shell_profiles_changed") is not False:
        raise ReconcileError("proposed reviewed evidence changed a shell profile")

    repeat = _require_exact_keys(
        value.get("repeat_install"), _EXPECTED_REPEAT_KEYS, "proposed repeat-install metadata"
    )
    if repeat.get("exit_code") != 0 or repeat.get("binary_hash_unchanged") is not True:
        raise ReconcileError("proposed repeat-install evidence did not preserve the admitted binary")
    behavior = repeat.get("behavior")
    if (
        not isinstance(behavior, str)
        or not behavior
        or len(behavior) > 1000
        or not behavior.isprintable()
    ):
        raise ReconcileError("proposed repeat-install behavior metadata is invalid")

    return installer_sha, payload_sha


def validate_discovery(value: dict[str, Any]) -> tuple[str, str]:
    """Validate static discovery and return its installer/payload pair."""
    try:
        DISCOVERY.validate_report(value)
    except (ValueError, RuntimeError) as exc:
        raise ReconcileError(f"proposed payload discovery is invalid: {exc}") from exc
    installer = value.get("installer")
    payload = value.get("payload")
    if not isinstance(installer, dict) or not isinstance(payload, dict):
        raise ReconcileError("proposed payload discovery metadata is malformed")
    return (
        sha256(installer.get("sha256"), "discovery installer SHA-256"),
        sha256(payload.get("sha256"), "discovery payload SHA-256"),
    )


def reconcile(
    *,
    live_detection: dict[str, Any],
    baseline_reviewed: dict[str, Any],
    live_discovery: dict[str, Any] | None,
    proposed_reviewed: dict[str, Any] | None,
    proposed_discovery: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
    """Select only evidence matching the current statically discovered hash pair."""
    live_installer = validate_detection(live_detection)
    baseline_installer_sha, baseline_payload_sha = validate_reviewed(
        baseline_reviewed, baseline=baseline_reviewed
    )
    detected_baseline_sha = sha256(
        live_detection.get("reviewed_installer_sha256"), "detected reviewed installer SHA-256"
    )
    if detected_baseline_sha != baseline_installer_sha:
        raise ReconcileError("live detection was not generated from the current reviewed baseline")
    live_installer_sha = live_installer["sha256"]
    baseline_pair = (baseline_installer_sha, baseline_payload_sha)

    live_discovery_pair: tuple[str, str] | None = None
    if live_discovery is not None:
        live_discovery_pair = validate_discovery(live_discovery)
        if live_discovery_pair[0] != live_installer_sha:
            raise ReconcileError("live payload discovery does not match the detected installer")

    selected_reviewed = baseline_reviewed
    selected_discovery: dict[str, Any] | None = None
    disposition = "baseline review + live detection"

    if proposed_reviewed is not None:
        proposed_pair = validate_reviewed(proposed_reviewed, baseline=baseline_reviewed)
        proposal_matches_live = (
            proposed_pair[0] == live_installer_sha
            and proposed_pair != baseline_pair
            and (live_discovery_pair is None or proposed_pair == live_discovery_pair)
        )
        if proposal_matches_live:
            selected_reviewed = proposed_reviewed
            disposition = "preserved full proposed evidence"

    if selected_reviewed is baseline_reviewed and live_discovery_pair is not None:
        if live_discovery_pair != baseline_pair:
            selected_discovery = live_discovery
            disposition = (
                "live payload change detected statically with reviewed installer"
                if live_installer_sha == baseline_installer_sha
                else "live installer/payload change detected statically"
            )

    if (
        selected_reviewed is baseline_reviewed
        and live_discovery_pair is None
        and proposed_discovery is not None
    ):
        proposed_discovery_pair = validate_discovery(proposed_discovery)
        if (
            proposed_discovery_pair[0] == live_installer_sha
            and proposed_discovery_pair != baseline_pair
        ):
            selected_discovery = proposed_discovery
            disposition = "preserved payload-discovery candidate"

    selected_installer_sha = selected_reviewed["installer"]["sha256"]
    normalized_detection = {
        "schema_version": 1,
        "kind": "antigravity-installer-detection",
        "installer": live_installer,
        "reviewed_installer_sha256": selected_installer_sha,
        "changed": live_installer_sha != selected_installer_sha,
    }
    return selected_reviewed, normalized_detection, selected_discovery, disposition


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-detection", type=Path, required=True)
    parser.add_argument("--baseline-reviewed", type=Path, required=True)
    parser.add_argument("--live-discovery", type=Path)
    parser.add_argument("--proposed-reviewed", type=Path)
    parser.add_argument("--proposed-discovery", type=Path)
    parser.add_argument("--reviewed-output", type=Path, required=True)
    parser.add_argument("--detection-output", type=Path, required=True)
    parser.add_argument("--discovery-output", type=Path)
    args = parser.parse_args()
    try:
        live_discovery = (
            load_json(args.live_discovery)
            if args.live_discovery is not None and args.live_discovery.exists()
            else None
        )
        proposed_reviewed = (
            load_json(args.proposed_reviewed)
            if args.proposed_reviewed is not None and args.proposed_reviewed.exists()
            else None
        )
        proposed_discovery = (
            load_json(args.proposed_discovery)
            if args.proposed_discovery is not None and args.proposed_discovery.exists()
            else None
        )
        reviewed, detection, discovery, disposition = reconcile(
            live_detection=load_json(args.live_detection),
            baseline_reviewed=load_json(args.baseline_reviewed),
            live_discovery=live_discovery,
            proposed_reviewed=proposed_reviewed,
            proposed_discovery=proposed_discovery,
        )
        args.reviewed_output.parent.mkdir(parents=True, exist_ok=True)
        args.detection_output.parent.mkdir(parents=True, exist_ok=True)
        args.reviewed_output.write_text(
            json.dumps(reviewed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        args.detection_output.write_text(
            json.dumps(detection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.discovery_output is not None:
            if discovery is None:
                args.discovery_output.unlink(missing_ok=True)
            else:
                args.discovery_output.parent.mkdir(parents=True, exist_ok=True)
                args.discovery_output.write_text(
                    json.dumps(discovery, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
    except (OSError, RuntimeError, ReconcileError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"Antigravity review state: {disposition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
