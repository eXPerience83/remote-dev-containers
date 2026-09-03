#!/usr/bin/env python3
"""Validate metadata-only Antigravity artifacts at workflow trust boundaries."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import urllib.parse
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parent
OFFICIAL_URL = "https://antigravity.google/cli/install.sh"
OFFICIAL_HOST = "antigravity.google"
MAX_BYTES = 2 * 1024 * 1024
MAX_NESTING_DEPTH = 64
SAFE_STRING_RE = re.compile(r"[ -~]{0,500}")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_KEYS = {
    "binary_bytes",
    "content_base64",
    "installer_bytes",
    "raw_binary",
    "raw_content",
    "stderr",
    "stderr_lines",
    "stdout",
    "stdout_lines",
}
INSPECTION_TOP_LEVEL = {
    "binary_after_first",
    "binary_after_second",
    "binary_stable_across_second_install",
    "blocking_findings",
    "environment_controls",
    "expected_binary_present",
    "filesystem",
    "first_install",
    "home_unchanged_after_help",
    "inspected_at_utc",
    "installed_legal_files",
    "installer",
    "platform",
    "profiles",
    "schema_version",
    "second_install",
}


class ArtifactError(ValueError):
    """Raised when an artifact crosses the workflow boundary unsafely."""


def load_module(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DETECT = load_module("antigravity_detect", "detect-antigravity-installer.py")
DISCOVER = load_module("antigravity_discover", "discover-antigravity-payload.py")
INSPECT = load_module("antigravity_inspect", "inspect-antigravity-cli.py")


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ArtifactError(f"could not read artifact {path}") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ArtifactError("Antigravity metadata artifact size is outside the supported boundary")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("Antigravity metadata artifact is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactError("Antigravity metadata artifact must contain one JSON object")
    return value


def validate_safe_tree(value: object, *, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise ArtifactError("Antigravity metadata nesting is too deep")
    if isinstance(value, dict):
        if len(value) > 200:
            raise ArtifactError("Antigravity metadata object is too large")
        for key, child in value.items():
            if not isinstance(key, str) or key in FORBIDDEN_KEYS:
                raise ArtifactError(f"Antigravity metadata contains forbidden key: {key!r}")
            if not SAFE_STRING_RE.fullmatch(key):
                raise ArtifactError("Antigravity metadata contains an unsafe key")
            validate_safe_tree(child, depth=depth + 1)
    elif isinstance(value, list):
        if len(value) > 1000:
            raise ArtifactError("Antigravity metadata list is too large")
        for child in value:
            validate_safe_tree(child, depth=depth + 1)
    elif isinstance(value, str):
        if not SAFE_STRING_RE.fullmatch(value):
            raise ArtifactError("Antigravity metadata contains non-printable or oversized text")
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise ArtifactError("Antigravity metadata contains an unsupported value type")


def exact_sha(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    normalized = value.lower()
    if not SHA256_RE.fullmatch(normalized):
        raise ArtifactError(f"{label} must be an exact SHA-256 value")
    return normalized


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


def require_official_installer(
    installer: object, *, allow_same_origin_redirect: bool = False
) -> dict[str, Any]:
    if not isinstance(installer, dict):
        raise ArtifactError("Antigravity installer metadata is malformed")
    if installer.get("source") != OFFICIAL_URL:
        raise ArtifactError("Antigravity artifact source is not the fixed official installer URL")
    final_url = installer.get("final_url")
    if allow_same_origin_redirect:
        if not safe_official_url(final_url):
            raise ArtifactError("Antigravity detection left the reviewed official HTTPS origin")
    elif final_url != OFFICIAL_URL:
        raise ArtifactError("Antigravity executable review does not use the fixed installer URL")
    return installer


def validate_detection(report: dict[str, Any], expected_installer: str | None) -> None:
    try:
        DETECT.validate_report(report)
    except (ValueError, RuntimeError, argparse.ArgumentTypeError) as exc:
        raise ArtifactError(f"Antigravity detection artifact is invalid: {exc}") from exc
    installer = require_official_installer(
        report.get("installer"), allow_same_origin_redirect=True
    )
    if expected_installer is not None and installer.get("sha256") != expected_installer:
        raise ArtifactError("Antigravity detection installer SHA-256 differs from the expected value")


def validate_discovery(report: dict[str, Any], expected_installer: str | None) -> None:
    try:
        DISCOVER.validate_report(report, expected_installer_sha256=expected_installer)
    except (ValueError, RuntimeError, argparse.ArgumentTypeError) as exc:
        raise ArtifactError(f"Antigravity payload-discovery artifact is invalid: {exc}") from exc
    require_official_installer(report.get("installer"))


def validate_inspection(
    report: dict[str, Any], expected_installer: str | None, expected_payload: str | None
) -> None:
    if set(report) != INSPECTION_TOP_LEVEL or report.get("schema_version") != 2:
        raise ArtifactError("Antigravity inspection artifact has an unsupported schema")
    errors = INSPECT.validate_report(report)
    if errors or report.get("blocking_findings") != []:
        raise ArtifactError(f"Antigravity inspection contains blocking findings: {errors!r}")
    installer = require_official_installer(report.get("installer"))
    binary = report.get("binary_after_second")
    if not isinstance(binary, dict):
        raise ArtifactError("Antigravity inspection has no normalized payload metadata")
    if expected_installer is not None and installer.get("sha256") != expected_installer:
        raise ArtifactError("Antigravity inspection installer SHA-256 differs from the admitted value")
    if expected_payload is not None and binary.get("sha256") != expected_payload:
        raise ArtifactError("Antigravity inspection payload SHA-256 differs from the admitted value")


def validate(
    report: dict[str, Any],
    *,
    kind: str,
    expected_installer: str | None,
    expected_payload: str | None,
) -> None:
    validate_safe_tree(report)
    if kind == "detection":
        validate_detection(report, expected_installer)
    elif kind == "discovery":
        if expected_installer is None:
            raise ArtifactError("payload discovery validation requires the admitted installer SHA-256")
        validate_discovery(report, expected_installer)
    elif kind == "inspection":
        if expected_installer is None or expected_payload is None:
            raise ArtifactError("full inspection validation requires admitted installer and payload hashes")
        validate_inspection(report, expected_installer, expected_payload)
    else:
        raise ArtifactError(f"unsupported Antigravity artifact kind: {kind}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("detection", "discovery", "inspection"), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--expected-installer-sha256")
    parser.add_argument("--expected-payload-sha256")
    args = parser.parse_args()
    try:
        expected_installer = exact_sha(args.expected_installer_sha256, "installer hash")
        expected_payload = exact_sha(args.expected_payload_sha256, "payload hash")
        validate(
            load_json(args.artifact),
            kind=args.kind,
            expected_installer=expected_installer,
            expected_payload=expected_payload,
        )
    except (OSError, RuntimeError, ArtifactError, RecursionError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print(f"Antigravity {args.kind} artifact: metadata-only schema OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
