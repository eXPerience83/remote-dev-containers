#!/usr/bin/env python3
"""Reconcile live Antigravity detection with optional proposed review state."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")
OFFICIAL_URL = "https://antigravity.google/cli/install.sh"
OFFICIAL_HOST = "antigravity.google"
EXPECTED_BINARY = ".local/bin/agy"
MAX_JSON_BYTES = 256 * 1024
MAX_PAYLOAD_BYTES = 512 * 1024 * 1024


class ReconcileError(ValueError):
    """Raised when persisted automation state violates the reviewed schema boundary."""


def load_json(path: Path) -> dict[str, Any]:
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
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ReconcileError(f"{label} is invalid")
    return value


def safe_official_url(value: object) -> bool:
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


def validate_detection(value: dict[str, Any]) -> dict[str, Any]:
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
    for preserved in ("workflow", "official_runtime_controls", "legal_and_distribution"):
        if value.get(preserved) != baseline.get(preserved):
            raise ReconcileError(f"proposed reviewed evidence changed human-owned {preserved}")
    installer = value.get("installer")
    binary = value.get("installed_binary")
    if not isinstance(installer, dict) or not isinstance(binary, dict):
        raise ReconcileError("proposed reviewed evidence is missing installer/binary metadata")
    if installer.get("official_url") != OFFICIAL_URL or installer.get("final_url") != OFFICIAL_URL:
        raise ReconcileError("proposed reviewed evidence changed the fixed installer origin")
    installer_sha = sha256(installer.get("sha256"), "proposed installer SHA-256")
    payload_sha = sha256(binary.get("sha256"), "proposed binary SHA-256")
    if binary.get("relative_path") != EXPECTED_BINARY:
        raise ReconcileError("proposed reviewed evidence changed the expected binary path")
    version = binary.get("version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise ReconcileError("proposed reviewed evidence has an invalid binary version")
    return installer_sha, payload_sha


def validate_discovery(value: dict[str, Any]) -> tuple[str, str]:
    expected_top = {
        "schema_version",
        "kind",
        "installer",
        "installation",
        "payload",
        "profiles_unchanged",
        "blocking_findings",
    }
    if set(value) != expected_top:
        raise ReconcileError("proposed payload discovery has unexpected fields")
    if value.get("schema_version") != 1 or value.get("kind") != "antigravity-payload-discovery":
        raise ReconcileError("proposed payload discovery has an unsupported schema")
    if value.get("blocking_findings") != [] or value.get("profiles_unchanged") is not True:
        raise ReconcileError("proposed payload discovery contains a blocking finding")

    installer = value.get("installer")
    installation = value.get("installation")
    payload = value.get("payload")
    if not isinstance(installer, dict) or not isinstance(installation, dict) or not isinstance(payload, dict):
        raise ReconcileError("proposed payload discovery metadata is malformed")
    installer_sha = sha256(installer.get("sha256"), "discovery installer SHA-256")
    if installer.get("source") != OFFICIAL_URL or installer.get("final_url") != OFFICIAL_URL:
        raise ReconcileError("proposed payload discovery changed the fixed installer origin")
    if installer.get("selected_strategy") not in {
        "custom-directory",
        "skip-shell-modification-flags",
    }:
        raise ReconcileError("proposed payload discovery used an unsupported installer strategy")
    if installation.get("exit_code") != 0:
        raise ReconcileError("proposed payload discovery installer did not succeed")
    if payload.get("path") != EXPECTED_BINARY:
        raise ReconcileError("proposed payload discovery changed the expected binary path")
    payload_sha = sha256(payload.get("sha256"), "discovery payload SHA-256")
    payload_size = payload.get("size")
    if not isinstance(payload_size, int) or not 0 < payload_size <= MAX_PAYLOAD_BYTES:
        raise ReconcileError("proposed payload discovery size is outside the supported boundary")
    return installer_sha, payload_sha


def reconcile(
    *,
    live_detection: dict[str, Any],
    baseline_reviewed: dict[str, Any],
    live_discovery: dict[str, Any] | None,
    proposed_reviewed: dict[str, Any] | None,
    proposed_discovery: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None, str]:
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
        if live_installer_sha != baseline_installer_sha:
            raise ReconcileError("live payload discovery executed an installer that was not already reviewed")

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
        if live_discovery_pair[1] != baseline_payload_sha:
            selected_discovery = live_discovery
            disposition = "live payload change detected with reviewed installer"

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
    except (OSError, ReconcileError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"Antigravity review state: {disposition}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
