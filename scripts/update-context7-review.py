#!/usr/bin/env python3
"""Validate npm metadata and update the reviewed transient Context7 CLI pins."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
from pathlib import Path

PACKAGE_NAME = "ctx7"
EXPECTED_LICENSE = "MIT"
REGISTRY = "https://registry.npmjs.org/"
MAX_METADATA_BYTES = 64 * 1024
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_ENV_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_HELPER_VERSION_RE = re.compile(
    r'^REVIEWED_CONTEXT7_CLI_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', re.MULTILINE
)
_HELPER_INTEGRITY_RE = re.compile(
    r'^REVIEWED_CONTEXT7_CLI_INTEGRITY = \(\n    "(sha512-[A-Za-z0-9+/=]+)"\n\)$',
    re.MULTILINE,
)
_TEST_CONSTANT_ASSERT_RE = re.compile(
    r'^(\s*if module\.REVIEWED_CONTEXT7_CLI_VERSION != ")([0-9]+\.[0-9]+\.[0-9]+)(":)$',
    re.MULTILINE,
)
_TEST_RESOLVED_ASSERT_RE = re.compile(
    r'^(\s*if module\.reviewed_cli_version\(\) != ")([0-9]+\.[0-9]+\.[0-9]+)(":)$',
    re.MULTILINE,
)


class MetadataError(ValueError):
    """Raised when registry metadata violates the reviewed Context7 contract."""


def exact_version(value: object) -> str:
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise MetadataError("Context7 CLI metadata must contain an exact stable version")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    exact_version(value)
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def parse_integrity(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("sha512-"):
        raise MetadataError("Context7 CLI metadata has no supported SHA-512 integrity")
    encoded = value.removeprefix("sha512-")
    if not encoded or any(character.isspace() for character in encoded):
        raise MetadataError("Context7 CLI SHA-512 integrity is malformed")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MetadataError("Context7 CLI SHA-512 integrity is malformed") from exc
    if len(decoded) != 64:
        raise MetadataError("Context7 CLI SHA-512 integrity is malformed")
    return value


def parse_metadata(path: Path) -> tuple[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MetadataError("Context7 registry metadata is unavailable") from exc
    if not raw or len(raw) > MAX_METADATA_BYTES:
        raise MetadataError("Context7 registry metadata size is outside the supported boundary")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataError("Context7 registry metadata is invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise MetadataError("Context7 registry metadata has an unexpected shape")

    name = payload.get("name")
    version = exact_version(payload.get("version"))
    license_name = payload.get("license")
    dist = payload.get("dist")
    if name != PACKAGE_NAME:
        raise MetadataError(f"unexpected Context7 package identity: {name!r}")
    if license_name != EXPECTED_LICENSE:
        raise MetadataError(
            f"Context7 CLI package license changed from {EXPECTED_LICENSE}: {license_name!r}"
        )
    if not isinstance(dist, dict):
        raise MetadataError("Context7 registry metadata has no dist object")
    integrity = parse_integrity(dist.get("integrity"))
    tarball = dist.get("tarball")
    expected_tarball = f"{REGISTRY}{PACKAGE_NAME}/-/{PACKAGE_NAME}-{version}.tgz"
    if tarball != expected_tarball:
        raise MetadataError("Context7 CLI metadata has an unexpected tarball URL")
    return version, integrity


def parse_versions(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_RE.fullmatch(line)
        if match is None:
            raise MetadataError(f"{path}:{line_number}: expected simple KEY=VALUE")
        key, value = match.groups()
        if key in values:
            raise MetadataError(f"{path}:{line_number}: duplicate key {key}")
        values[key] = value
    return values


def replace_env(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise MetadataError(f"versions.env must contain exactly one {key} assignment")
    return pattern.sub(f"{key}={value}", text, count=1)


def replace_helper(text: str, version: str, integrity: str) -> str:
    version_matches = list(_HELPER_VERSION_RE.finditer(text))
    integrity_matches = list(_HELPER_INTEGRITY_RE.finditer(text))
    if len(version_matches) != 1 or len(integrity_matches) != 1:
        raise MetadataError("Context7 helper reviewed-pin constants are malformed")
    text = _HELPER_VERSION_RE.sub(
        f'REVIEWED_CONTEXT7_CLI_VERSION = "{version}"', text, count=1
    )
    text = _HELPER_INTEGRITY_RE.sub(
        'REVIEWED_CONTEXT7_CLI_INTEGRITY = (\n'
        f'    "{integrity}"\n'
        ')',
        text,
        count=1,
    )
    return text


def replace_reviewed_test_assertions(text: str, current: str, new: str) -> str:
    constant_matches = list(_TEST_CONSTANT_ASSERT_RE.finditer(text))
    resolved_matches = list(_TEST_RESOLVED_ASSERT_RE.finditer(text))
    if len(constant_matches) != 1 or len(resolved_matches) != 1:
        raise MetadataError("Context7 reviewed-version test assertions are malformed")
    if constant_matches[0].group(2) != current or resolved_matches[0].group(2) != current:
        raise MetadataError("Context7 reviewed-version tests disagree with the current reviewed pin")
    text = _TEST_CONSTANT_ASSERT_RE.sub(rf'\g<1>{new}\g<3>', text, count=1)
    text = _TEST_RESOLVED_ASSERT_RE.sub(rf'\g<1>{new}\g<3>', text, count=1)
    return text


def update(
    metadata: Path,
    versions_path: Path,
    helper_path: Path,
    *,
    write: bool,
    test_path: Path | None = None,
) -> bool:
    latest_version, latest_integrity = parse_metadata(metadata)
    values = parse_versions(versions_path)
    current_version = exact_version(values.get("CONTEXT7_CLI_VERSION"))
    current_integrity = parse_integrity(values.get("CONTEXT7_CLI_SRI_SHA512"))

    helper_text = helper_path.read_text(encoding="utf-8")
    helper_version = _HELPER_VERSION_RE.search(helper_text)
    helper_integrity = _HELPER_INTEGRITY_RE.search(helper_text)
    if helper_version is None or helper_integrity is None:
        raise MetadataError("Context7 helper reviewed-pin constants are malformed")
    if helper_version.group(1) != current_version or helper_integrity.group(1) != current_integrity:
        raise MetadataError("versions.env and Context7 helper reviewed pins are inconsistent")

    test_text: str | None = None
    if test_path is not None:
        test_text = test_path.read_text(encoding="utf-8")
        # Validate synchronization even when no update is needed.
        replace_reviewed_test_assertions(test_text, current_version, current_version)

    if version_tuple(latest_version) < version_tuple(current_version):
        raise MetadataError(
            f"registry latest Context7 version regressed: {latest_version} < {current_version}"
        )

    changed = latest_version != current_version or latest_integrity != current_integrity
    if not changed:
        print(f"Context7 CLI already current at {current_version}")
        return False

    if latest_version == current_version and latest_integrity != current_integrity:
        raise MetadataError(
            "Context7 registry changed integrity for the already reviewed version; require focused review"
        )

    versions_text = versions_path.read_text(encoding="utf-8")
    updated_versions = replace_env(versions_text, "CONTEXT7_CLI_VERSION", latest_version)
    updated_versions = replace_env(
        updated_versions, "CONTEXT7_CLI_SRI_SHA512", latest_integrity
    )
    updated_helper = replace_helper(helper_text, latest_version, latest_integrity)
    updated_test = (
        replace_reviewed_test_assertions(test_text, current_version, latest_version)
        if test_text is not None
        else None
    )

    if write:
        versions_path.write_text(updated_versions, encoding="utf-8")
        helper_path.write_text(updated_helper, encoding="utf-8")
        if test_path is not None and updated_test is not None:
            test_path.write_text(updated_test, encoding="utf-8")
    print(f"Context7 CLI update: {current_version} -> {latest_version}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--versions", type=Path, default=Path("versions.env"))
    parser.add_argument(
        "--helper", type=Path, default=Path("scripts/remote-dev-context7-device-login.py")
    )
    parser.add_argument(
        "--test",
        type=Path,
        default=Path("scripts/test-remote-dev-context7-device-login.py"),
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        update(
            args.metadata,
            args.versions,
            args.helper,
            write=args.write,
            test_path=args.test,
        )
    except (OSError, MetadataError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
