#!/usr/bin/env python3
"""Discover the Antigravity payload hash without executing vendor code.

The admitted installer is treated only as data. Its exact hash and reviewed
manifest-contract markers are verified, then the fixed Google manifest and
archive are downloaded with strict redirect policies. The archive SHA-512 is
verified and the `antigravity` member is hashed directly from the tar stream;
neither the installer nor the resulting `agy` payload is executed or extracted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import re
import tarfile
import tempfile
import urllib.parse
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

MANIFEST_URL = (
    "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/"
    "manifests/linux_amd64.json"
)
MANIFEST_HOST = "antigravity-cli-auto-updater-974169037036.us-central1.run.app"
PAYLOAD_HOST = "storage.googleapis.com"
EXPECTED_ARCHIVE_MEMBER = "antigravity"
MAX_MANIFEST_SIZE = 64 * 1024
MAX_ARCHIVE_SIZE = 512 * 1024 * 1024
MAX_PAYLOAD_SIZE = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA512_RE = re.compile(r"^[0-9a-fA-F]{128}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_PAYLOAD_PATH_RE = re.compile(
    r"^/antigravity-public/antigravity-cli/"
    r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+/linux-x64/cli_linux_x64\.tar\.gz$"
)
_INSTALLER_CONTRACT_MARKERS = (
    b"antigravity-cli-auto-updater-974169037036.us-central1.run.app",
    b"/manifests/",
    b"sha512",
)


class DiscoveryError(ValueError):
    """Raised when static payload discovery violates the reviewed contract."""


def _strict_https_url(url: object, *, host: str, path: str | None = None) -> bool:
    if not isinstance(url, str) or not url or "\\" in url:
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme != "https"
        or parsed.hostname != host
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    return path is None or parsed.path == path


def installer_url_policy(url: str) -> bool:
    return url == INSPECTOR.OFFICIAL_INSTALLER_URL


def manifest_url_policy(url: str) -> bool:
    return _strict_https_url(
        url,
        host=MANIFEST_HOST,
        path="/manifests/linux_amd64.json",
    )


def payload_url_policy(url: str) -> bool:
    if not _strict_https_url(url, host=PAYLOAD_HOST):
        return False
    parsed = urllib.parse.urlsplit(url)
    return bool(_PAYLOAD_PATH_RE.fullmatch(parsed.path))


def _fixture_bytes(path: Path, *, max_bytes: int, label: str) -> bytes:
    data = path.read_bytes()
    if not data or len(data) > max_bytes:
        raise DiscoveryError(f"{label} fixture is outside the supported size boundary")
    return data


def _installer_contract(data: bytes) -> None:
    missing = [
        marker.decode("ascii")
        for marker in _INSTALLER_CONTRACT_MARKERS
        if marker not in data
    ]
    if missing:
        raise DiscoveryError(
            "admitted installer no longer exposes the reviewed manifest/checksum contract"
        )


def _load_installer(
    *, expected_installer_sha256: str, installer_fixture: Path | None, root: Path
) -> tuple[bytes, str | None, str, str]:
    destination = root / "install.sh"
    fixture = installer_fixture is not None
    if fixture:
        data, content_type, final_url = INSPECTOR.load_local_installer(
            installer_fixture, destination
        )
        source = final_url
    else:
        try:
            data, content_type, final_url = NETWORK.download_bytes(
                INSPECTOR.OFFICIAL_INSTALLER_URL,
                destination,
                max_bytes=2 * 1024 * 1024,
                policy=installer_url_policy,
                user_agent="remote-dev-containers-antigravity-discovery",
            )
        except NETWORK.DownloadError as exc:
            raise DiscoveryError(str(exc)) from exc
        source = INSPECTOR.OFFICIAL_INSTALLER_URL

    installer_sha256 = INSPECTOR.sha256_bytes(data)
    if installer_sha256 != expected_installer_sha256:
        raise DiscoveryError(
            "installer SHA-256 differs from the explicitly admitted value"
        )
    if not fixture and final_url != INSPECTOR.OFFICIAL_INSTALLER_URL:
        raise DiscoveryError("admitted installer redirected unexpectedly")
    _installer_contract(data)
    return data, content_type, final_url, source


def _parse_manifest(data: bytes) -> tuple[str, str, str]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryError("Antigravity manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != {"version", "url", "sha512"}:
        raise DiscoveryError("Antigravity manifest schema changed")
    version = value.get("version")
    payload_url = value.get("url")
    archive_sha512 = value.get("sha512")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise DiscoveryError("Antigravity manifest version is not an exact stable version")
    if not isinstance(payload_url, str) or not payload_url_policy(payload_url):
        raise DiscoveryError(
            "Antigravity manifest payload URL left the reviewed Google archive path"
        )
    if not isinstance(archive_sha512, str) or not _SHA512_RE.fullmatch(archive_sha512):
        raise DiscoveryError("Antigravity manifest SHA-512 is malformed")
    if f"/{version}-" not in urllib.parse.urlsplit(payload_url).path:
        raise DiscoveryError("Antigravity manifest version does not match its payload URL")
    return version, payload_url, archive_sha512.lower()


def _hash_payload_from_archive(data: bytes) -> tuple[int, str]:
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            payload_member = None
            member_count = 0
            for member in archive:
                member_count += 1
                if member_count > MAX_ARCHIVE_MEMBERS:
                    raise DiscoveryError(
                        "Antigravity archive member count is outside the reviewed boundary"
                    )
                normalized = (
                    member.name[2:] if member.name.startswith("./") else member.name
                )
                if member.issym() or member.islnk() or member.isdev():
                    raise DiscoveryError(
                        "Antigravity archive contains an unsupported link/device member"
                    )
                if member.isfile():
                    if normalized != EXPECTED_ARCHIVE_MEMBER:
                        raise DiscoveryError(
                            "Antigravity archive contains an unexpected regular file"
                        )
                    if payload_member is not None:
                        raise DiscoveryError(
                            "Antigravity archive contains multiple payload members"
                        )
                    if not 0 < member.size <= MAX_PAYLOAD_SIZE:
                        raise DiscoveryError(
                            "Antigravity archive payload size is outside the reviewed boundary"
                        )
                    payload_member = member
                elif not member.isdir():
                    raise DiscoveryError(
                        "Antigravity archive contains an unsupported member type"
                    )
            if member_count == 0 or payload_member is None:
                raise DiscoveryError(
                    "Antigravity archive does not contain exactly one payload member"
                )
            stream = archive.extractfile(payload_member)
            if stream is None:
                raise DiscoveryError("Antigravity archive payload cannot be read")
            digest = hashlib.sha256()
            total = 0
            while chunk := stream.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_PAYLOAD_SIZE:
                    raise DiscoveryError(
                        "Antigravity archive payload exceeds the reviewed boundary"
                    )
                digest.update(chunk)
            if total != payload_member.size:
                raise DiscoveryError("Antigravity archive payload size is inconsistent")
            return total, digest.hexdigest()
    except (tarfile.TarError, OSError) as exc:
        raise DiscoveryError("Antigravity payload archive is malformed") from exc


def discover(
    *,
    expected_installer_sha256: str,
    installer_fixture: Path | None,
    manifest_fixture: Path | None = None,
    archive_fixture: Path | None = None,
) -> dict[str, Any]:
    fixtures = (installer_fixture, manifest_fixture, archive_fixture)
    if any(item is not None for item in fixtures) and not all(
        item is not None for item in fixtures
    ):
        raise DiscoveryError(
            "offline discovery fixtures must provide installer, manifest and archive together"
        )
    fixture_mode = installer_fixture is not None

    with tempfile.TemporaryDirectory(prefix="antigravity-payload-discovery-") as temporary:
        root = Path(temporary)
        (
            installer_data,
            installer_content_type,
            installer_final_url,
            installer_source,
        ) = _load_installer(
            expected_installer_sha256=expected_installer_sha256,
            installer_fixture=installer_fixture,
            root=root,
        )

        if fixture_mode:
            assert manifest_fixture is not None
            manifest_data = _fixture_bytes(
                manifest_fixture, max_bytes=MAX_MANIFEST_SIZE, label="manifest"
            )
            manifest_content_type = "application/json"
            manifest_final_url = f"fixture:{manifest_fixture.name}"
            manifest_source = manifest_final_url
        else:
            try:
                (
                    manifest_data,
                    manifest_content_type,
                    manifest_final_url,
                ) = NETWORK.download_bytes(
                    MANIFEST_URL,
                    root / "manifest.json",
                    max_bytes=MAX_MANIFEST_SIZE,
                    policy=manifest_url_policy,
                    user_agent="remote-dev-containers-antigravity-discovery",
                )
            except NETWORK.DownloadError as exc:
                raise DiscoveryError(str(exc)) from exc
            manifest_source = MANIFEST_URL
            if manifest_final_url != MANIFEST_URL:
                raise DiscoveryError("Antigravity manifest redirected unexpectedly")

        version, payload_url, expected_archive_sha512 = _parse_manifest(manifest_data)

        if fixture_mode:
            assert archive_fixture is not None
            archive_data = _fixture_bytes(
                archive_fixture, max_bytes=MAX_ARCHIVE_SIZE, label="archive"
            )
            archive_content_type = "application/gzip"
            archive_final_url = f"fixture:{archive_fixture.name}"
            archive_source = archive_final_url
        else:
            try:
                (
                    archive_data,
                    archive_content_type,
                    archive_final_url,
                ) = NETWORK.download_bytes(
                    payload_url,
                    root / "payload.tar.gz",
                    max_bytes=MAX_ARCHIVE_SIZE,
                    policy=payload_url_policy,
                    user_agent="remote-dev-containers-antigravity-discovery",
                    timeout=300,
                )
            except NETWORK.DownloadError as exc:
                raise DiscoveryError(str(exc)) from exc
            archive_source = payload_url
            if archive_final_url != payload_url:
                raise DiscoveryError("Antigravity payload archive redirected unexpectedly")

        archive_sha512 = hashlib.sha512(archive_data).hexdigest()
        if archive_sha512 != expected_archive_sha512:
            raise DiscoveryError(
                "Antigravity archive SHA-512 differs from the official manifest"
            )
        payload_size, payload_sha256 = _hash_payload_from_archive(archive_data)

        report = {
            "schema_version": 2,
            "kind": "antigravity-payload-discovery",
            "installer": {
                "source": installer_source,
                "final_url": installer_final_url,
                "content_type": installer_content_type,
                "size": len(installer_data),
                "sha256": INSPECTOR.sha256_bytes(installer_data),
                "manifest_url": MANIFEST_URL,
                "archive_member": EXPECTED_ARCHIVE_MEMBER,
            },
            "manifest": {
                "source": manifest_source,
                "final_url": manifest_final_url,
                "content_type": manifest_content_type,
                "size": len(manifest_data),
                "sha256": INSPECTOR.sha256_bytes(manifest_data),
                "version": version,
                "payload_url": payload_url,
                "payload_sha512": expected_archive_sha512,
            },
            "archive": {
                "source": archive_source,
                "final_url": archive_final_url,
                "content_type": archive_content_type,
                "size": len(archive_data),
                "sha512": archive_sha512,
                "member": EXPECTED_ARCHIVE_MEMBER,
            },
            "payload": {
                "path": INSPECTOR.EXPECTED_BINARY.as_posix(),
                "size": payload_size,
                "sha256": payload_sha256,
            },
            "blocking_findings": [],
        }
        validate_report(
            report,
            expected_installer_sha256=expected_installer_sha256,
            allow_fixtures=fixture_mode,
        )
        return report


def _valid_content_type(value: object) -> bool:
    return value is None or (
        isinstance(value, str)
        and len(value) <= 200
        and all(ord(character) >= 0x20 for character in value)
    )


def validate_report(
    report: dict[str, Any],
    *,
    expected_installer_sha256: str | None = None,
    allow_fixtures: bool = False,
) -> None:
    if set(report) != {
        "schema_version",
        "kind",
        "installer",
        "manifest",
        "archive",
        "payload",
        "blocking_findings",
    }:
        raise DiscoveryError("payload discovery report has unexpected top-level fields")
    if report.get("schema_version") != 2 or report.get(
        "kind"
    ) != "antigravity-payload-discovery":
        raise DiscoveryError("payload discovery report has an unsupported schema")
    if report.get("blocking_findings") != []:
        raise DiscoveryError("payload discovery report contains a blocking finding")

    installer = report.get("installer")
    manifest = report.get("manifest")
    archive = report.get("archive")
    payload = report.get("payload")
    if not isinstance(installer, dict) or set(installer) != {
        "source",
        "final_url",
        "content_type",
        "size",
        "sha256",
        "manifest_url",
        "archive_member",
    }:
        raise DiscoveryError("payload discovery installer metadata is malformed")
    if not isinstance(manifest, dict) or set(manifest) != {
        "source",
        "final_url",
        "content_type",
        "size",
        "sha256",
        "version",
        "payload_url",
        "payload_sha512",
    }:
        raise DiscoveryError("payload discovery manifest metadata is malformed")
    if not isinstance(archive, dict) or set(archive) != {
        "source",
        "final_url",
        "content_type",
        "size",
        "sha512",
        "member",
    }:
        raise DiscoveryError("payload discovery archive metadata is malformed")
    if not isinstance(payload, dict) or set(payload) != {"path", "size", "sha256"}:
        raise DiscoveryError("payload discovery payload metadata is malformed")

    installer_sha = installer.get("sha256")
    if not isinstance(installer_sha, str) or not _SHA256_RE.fullmatch(installer_sha):
        raise DiscoveryError("payload discovery installer SHA-256 is invalid")
    if expected_installer_sha256 is not None and installer_sha != expected_installer_sha256:
        raise DiscoveryError(
            "payload discovery installer SHA-256 differs from the admitted value"
        )
    if (
        installer.get("manifest_url") != MANIFEST_URL
        or installer.get("archive_member") != EXPECTED_ARCHIVE_MEMBER
    ):
        raise DiscoveryError("payload discovery installer contract metadata changed")
    if not isinstance(installer.get("size"), int) or not 0 < installer[
        "size"
    ] <= 2 * 1024 * 1024:
        raise DiscoveryError("payload discovery installer size is invalid")
    if not _valid_content_type(installer.get("content_type")):
        raise DiscoveryError("payload discovery installer content type is invalid")

    version = manifest.get("version")
    payload_url = manifest.get("payload_url")
    payload_sha512 = manifest.get("payload_sha512")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise DiscoveryError("payload discovery manifest version is invalid")
    if not isinstance(payload_url, str) or not payload_url_policy(payload_url):
        raise DiscoveryError("payload discovery manifest payload URL is invalid")
    if not isinstance(payload_sha512, str) or not re.fullmatch(
        r"[0-9a-f]{128}", payload_sha512
    ):
        raise DiscoveryError("payload discovery manifest SHA-512 is invalid")
    if not isinstance(manifest.get("sha256"), str) or not _SHA256_RE.fullmatch(
        manifest["sha256"]
    ):
        raise DiscoveryError("payload discovery manifest SHA-256 is invalid")
    if not isinstance(manifest.get("size"), int) or not 0 < manifest[
        "size"
    ] <= MAX_MANIFEST_SIZE:
        raise DiscoveryError("payload discovery manifest size is invalid")
    if not _valid_content_type(manifest.get("content_type")):
        raise DiscoveryError("payload discovery manifest content type is invalid")

    if (
        archive.get("sha512") != payload_sha512
        or archive.get("member") != EXPECTED_ARCHIVE_MEMBER
    ):
        raise DiscoveryError("payload discovery archive identity is inconsistent")
    if not isinstance(archive.get("size"), int) or not 0 < archive[
        "size"
    ] <= MAX_ARCHIVE_SIZE:
        raise DiscoveryError("payload discovery archive size is invalid")
    if not _valid_content_type(archive.get("content_type")):
        raise DiscoveryError("payload discovery archive content type is invalid")

    payload_sha = payload.get("sha256")
    if not isinstance(payload_sha, str) or not _SHA256_RE.fullmatch(payload_sha):
        raise DiscoveryError("payload discovery binary SHA-256 is invalid")
    if payload.get("path") != INSPECTOR.EXPECTED_BINARY.as_posix():
        raise DiscoveryError("payload discovery path is unexpected")
    payload_size = payload.get("size")
    if not isinstance(payload_size, int) or not 0 < payload_size <= MAX_PAYLOAD_SIZE:
        raise DiscoveryError("payload discovery payload size is invalid")

    if allow_fixtures:
        for record in (installer, manifest, archive):
            if not isinstance(record.get("source"), str) or not record[
                "source"
            ].startswith("fixture:"):
                raise DiscoveryError("offline payload discovery source is not a fixture")
            if record.get("final_url") != record.get("source"):
                raise DiscoveryError(
                    "offline payload discovery fixture URL is inconsistent"
                )
    else:
        if (
            installer.get("source") != INSPECTOR.OFFICIAL_INSTALLER_URL
            or installer.get("final_url") != INSPECTOR.OFFICIAL_INSTALLER_URL
        ):
            raise DiscoveryError(
                "payload discovery installer left the fixed official URL"
            )
        if (
            manifest.get("source") != MANIFEST_URL
            or manifest.get("final_url") != MANIFEST_URL
        ):
            raise DiscoveryError("payload discovery manifest left the fixed reviewed URL")
        if archive.get("source") != payload_url or archive.get(
            "final_url"
        ) != payload_url:
            raise DiscoveryError(
                "payload discovery archive left the manifest-selected URL"
            )


def write_report(
    output: Path,
    *,
    expected_installer_sha256: str,
    installer_fixture: Path | None,
    manifest_fixture: Path | None = None,
    archive_fixture: Path | None = None,
) -> dict[str, Any]:
    report = discover(
        expected_installer_sha256=expected_installer_sha256,
        installer_fixture=installer_fixture,
        manifest_fixture=manifest_fixture,
        archive_fixture=archive_fixture,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-installer-sha256", type=INSPECTOR.parse_sha256, required=True
    )
    parser.add_argument("--installer-fixture", type=Path)
    parser.add_argument("--manifest-fixture", type=Path)
    parser.add_argument("--archive-fixture", type=Path)
    args = parser.parse_args()
    try:
        write_report(
            args.output,
            expected_installer_sha256=args.expected_installer_sha256,
            installer_fixture=args.installer_fixture,
            manifest_fixture=args.manifest_fixture,
            archive_fixture=args.archive_fixture,
        )
    except (OSError, RuntimeError, DiscoveryError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print("Antigravity payload discovery: OK (installer and payload not executed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
