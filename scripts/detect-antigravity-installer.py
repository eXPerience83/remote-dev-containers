#!/usr/bin/env python3
"""Detect bounded Antigravity installer metadata without executing vendor bytes."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import tempfile
from pathlib import Path
from typing import Any

import antigravity_download as NETWORK

ROOT = Path(__file__).resolve().parent
INSPECTOR_PATH = ROOT / "inspect-antigravity-cli.py"
SPEC = importlib.util.spec_from_file_location("antigravity_inspector", INSPECTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load inspect-antigravity-cli.py")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)

_HOST_RE = re.compile(rb"https://([A-Za-z0-9.-]{1,253})(?=[:/\"'\s]|$)")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_INSTALLER_BYTES = 2 * 1024 * 1024


class DetectionError(ValueError):
    """Raised when detection metadata violates the fixed review contract."""


def parse_sha256(value: str) -> str:
    """Normalize one explicit SHA-256 value."""
    normalized = value.lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise argparse.ArgumentTypeError("expected a 64-character SHA-256 value")
    return normalized


def installer_url_policy(url: str) -> bool:
    """Allow only the exact canonical official installer URL."""
    return url == INSPECTOR.OFFICIAL_INSTALLER_URL


def valid_hostname(host: str) -> bool:
    """Return whether host is a conservative normalized DNS hostname."""
    if len(host) > 253 or host.startswith(".") or host.endswith("."):
        return False
    labels = host.split(".")
    return all(
        label
        and len(label) <= 63
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label)
        for label in labels
    )


def referenced_https_hosts(data: bytes) -> list[str]:
    """Extract only normalized HTTPS host names from installer text."""
    hosts: set[str] = set()
    for match in _HOST_RE.finditer(data):
        try:
            host = match.group(1).decode("ascii").lower()
        except UnicodeDecodeError:
            continue
        if valid_hostname(host):
            hosts.add(host)
    return sorted(hosts)


def detect(
    *,
    reviewed_installer_sha256: str,
    installer_fixture: Path | None,
) -> dict[str, Any]:
    """Fetch or load installer bytes and emit metadata without execution."""
    with tempfile.TemporaryDirectory(prefix="antigravity-detection-") as temporary:
        destination = Path(temporary) / "install.sh"
        if installer_fixture is None:
            try:
                data, content_type, final_url = NETWORK.download_bytes(
                    INSPECTOR.OFFICIAL_INSTALLER_URL,
                    destination,
                    max_bytes=MAX_INSTALLER_BYTES,
                    policy=installer_url_policy,
                    user_agent="remote-dev-containers-antigravity-detection",
                )
            except NETWORK.DownloadError as exc:
                raise DetectionError(str(exc)) from exc
            if final_url != INSPECTOR.OFFICIAL_INSTALLER_URL:
                raise DetectionError("official installer redirected unexpectedly")
            source = INSPECTOR.OFFICIAL_INSTALLER_URL
        else:
            data, content_type, final_url = INSPECTOR.load_local_installer(
                installer_fixture, destination
            )
            source = final_url

        actual_sha256 = INSPECTOR.sha256_bytes(data)
        return {
            "schema_version": 1,
            "kind": "antigravity-installer-detection",
            "installer": {
                "source": source,
                "final_url": final_url,
                "content_type": content_type,
                "size": len(data),
                "sha256": actual_sha256,
                "referenced_https_hosts": referenced_https_hosts(data),
            },
            "reviewed_installer_sha256": reviewed_installer_sha256,
            "changed": actual_sha256 != reviewed_installer_sha256,
        }


def validate_report(report: dict[str, Any]) -> None:
    """Validate the normalized metadata-only detector schema."""
    if set(report) != {
        "schema_version",
        "kind",
        "installer",
        "reviewed_installer_sha256",
        "changed",
    }:
        raise DetectionError("Antigravity detection report has unexpected top-level fields")
    if report["schema_version"] != 1 or report["kind"] != "antigravity-installer-detection":
        raise DetectionError("Antigravity detection report has an unsupported schema")
    if not isinstance(report["changed"], bool):
        raise DetectionError("Antigravity detection changed flag is invalid")
    reviewed = report["reviewed_installer_sha256"]
    if not isinstance(reviewed, str) or not _SHA256_RE.fullmatch(reviewed):
        raise DetectionError("reviewed installer SHA-256 is invalid")
    installer = report["installer"]
    if not isinstance(installer, dict) or set(installer) != {
        "source",
        "final_url",
        "content_type",
        "size",
        "sha256",
        "referenced_https_hosts",
    }:
        raise DetectionError("Antigravity detection installer metadata is malformed")
    for field in ("source", "final_url"):
        if not isinstance(installer[field], str) or not installer[field] or len(installer[field]) > 500:
            raise DetectionError(f"detected installer {field} is invalid")
    content_type = installer["content_type"]
    if content_type is not None and (
        not isinstance(content_type, str)
        or len(content_type) > 200
        or any(ord(character) < 0x20 for character in content_type)
    ):
        raise DetectionError("detected installer content type is invalid")
    sha256 = installer["sha256"]
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise DetectionError("detected installer SHA-256 is invalid")
    size = installer["size"]
    if not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise DetectionError("detected installer size is outside the supported boundary")
    hosts = installer["referenced_https_hosts"]
    if not isinstance(hosts, list) or hosts != sorted(set(hosts)) or len(hosts) > 100:
        raise DetectionError("detected installer host list is not normalized")
    if any(not isinstance(host, str) or not valid_hostname(host) for host in hosts):
        raise DetectionError("detected installer host list contains an invalid hostname")
    if report["changed"] != (sha256 != reviewed):
        raise DetectionError("Antigravity detection changed flag is inconsistent")


def write_report(
    output: Path,
    *,
    reviewed_installer_sha256: str,
    installer_fixture: Path | None,
) -> dict[str, Any]:
    """Write validated detector metadata to disk."""
    report = detect(
        reviewed_installer_sha256=reviewed_installer_sha256,
        installer_fixture=installer_fixture,
    )
    validate_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed-installer-sha256", type=parse_sha256, required=True)
    parser.add_argument("--installer-fixture", type=Path)
    args = parser.parse_args()
    try:
        report = write_report(
            args.output,
            reviewed_installer_sha256=args.reviewed_installer_sha256,
            installer_fixture=args.installer_fixture,
        )
    except (OSError, RuntimeError, DetectionError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print(
        "Antigravity installer detection: changed"
        if report["changed"]
        else "Antigravity installer detection: current"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
