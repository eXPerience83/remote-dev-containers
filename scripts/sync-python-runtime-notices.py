#!/usr/bin/env python3
"""Preserve legal metadata from the exact Python standalone distributions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, NoReturn

API_ROOT = "https://api.github.com/repos/astral-sh/python-build-standalone"
ALLOWED_HOSTS = frozenset({"api.github.com", "github.com", "objects.githubusercontent.com"})
FULL_BUILD_PREFERENCE = ("pgo+lto", "pgo", "lto", "noopt")
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
USER_AGENT = "remote-dev-containers python runtime notice synchronizer"
URL_PATTERN = re.compile(
    r'url\s*=\s*"(?P<url>https://github\.com/astral-sh/python-build-standalone/'
    r'releases/download/(?P<release>[0-9]+)/'
    r'cpython-(?P<version>[^+\"]+)\+(?P=release)-'
    r'(?P<target>(?:x86_64|aarch64)-unknown-linux-gnu)-'
    r'install_only_stripped\.tar\.gz)"'
)
ARCH_NAMES = {"x86_64-unknown-linux-gnu": "amd64", "aarch64-unknown-linux-gnu": "arm64"}


def fail(message: str) -> NoReturn:
    """Exit with a consistent error."""
    raise SystemExit(f"ERROR: {message}")


def validate_url(url: str) -> None:
    """Restrict network requests to the expected HTTPS hosts."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        fail(f"URL must use HTTPS: {url}")
    if parsed.username or parsed.password:
        fail(f"URL must not contain credentials: {url}")
    host = parsed.hostname.lower()
    if host not in ALLOWED_HOSTS and not host.endswith(".githubusercontent.com"):
        fail(f"URL host is not approved: {url}")


def request_bytes(url: str, token: str | None = None, limit: int | None = None) -> bytes:
    """Download one bounded response and validate redirects."""
    validate_url(url)
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            validate_url(response.geturl())
            data = response.read(None if limit is None else limit + 1)
    except (OSError, urllib.error.HTTPError) as exc:
        fail(f"cannot download {url}: {exc}")
    if limit is not None and len(data) > limit:
        fail(f"download exceeds {limit} bytes: {url}")
    return data


def request_json(url: str, token: str | None = None) -> Any:
    """Download and parse one GitHub JSON response."""
    try:
        return json.loads(request_bytes(url, token=token, limit=20 * 1024 * 1024))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON from {url}: {exc}")


def parse_install_artifacts(lock_path: Path) -> list[dict[str, str]]:
    """Read the two exact Python install-only artifact URLs from mise.lock."""
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {lock_path}: {exc}")

    records: dict[str, dict[str, str]] = {}
    for match in URL_PATTERN.finditer(text):
        target = match.group("target")
        arch = ARCH_NAMES[target]
        record = {
            "arch": arch,
            "target": target,
            "python_version": match.group("version"),
            "release": match.group("release"),
            "install_asset_url": match.group("url"),
        }
        if arch in records and records[arch] != record:
            fail(f"mise.lock contains conflicting Python artifacts for {arch}")
        records[arch] = record

    if set(records) != {"amd64", "arm64"}:
        fail("mise.lock must contain exact amd64 and arm64 Python install-only artifacts")
    versions = {record["python_version"] for record in records.values()}
    releases = {record["release"] for record in records.values()}
    if len(versions) != 1 or len(releases) != 1:
        fail("Python artifacts must use one version and one standalone release")
    return [records["amd64"], records["arm64"]]


def list_release_assets(release: str, token: str | None) -> dict[str, dict[str, Any]]:
    """Return every asset from one immutable upstream release."""
    release_url = f"{API_ROOT}/releases/tags/{release}"
    release_data = request_json(release_url, token)
    if not isinstance(release_data, dict):
        fail(f"unexpected release response for {release}")
    assets_url = release_data.get("assets_url")
    if not isinstance(assets_url, str):
        fail(f"release {release} has no assets URL")

    assets: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        separator = "&" if "?" in assets_url else "?"
        page_url = f"{assets_url}{separator}per_page=100&page={page}"
        page_data = request_json(page_url, token)
        if not isinstance(page_data, list):
            fail(f"unexpected assets response for release {release}")
        for asset in page_data:
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
                fail(f"release {release} contains a malformed asset record")
            assets[asset["name"]] = asset
        if len(page_data) < 100:
            break
        page += 1
        if page > 20:
            fail(f"release {release} has unexpectedly many asset pages")
    return assets


def select_full_asset(record: dict[str, str], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Select the full archive that upstream uses for install-only output."""
    prefix = (
        f"cpython-{record['python_version']}+{record['release']}-"
        f"{record['target']}-"
    )
    for build in FULL_BUILD_PREFERENCE:
        name = f"{prefix}{build}-full.tar.zst"
        asset = assets.get(name)
        if asset is not None:
            return asset
    fail(f"no supported full distribution found for {record['arch']}: {prefix}")


def download_verified_asset(asset: dict[str, Any], token: str | None, destination: Path) -> str:
    """Download a release asset and verify its GitHub-published SHA-256."""
    name = asset.get("name")
    url = asset.get("browser_download_url")
    digest = asset.get("digest")
    size = asset.get("size")
    if not isinstance(name, str) or not isinstance(url, str):
        fail("release asset lacks a name or download URL")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        fail(f"release asset lacks a valid SHA-256 digest: {name}")
    if not isinstance(size, int) or size <= 0 or size > MAX_ARCHIVE_BYTES:
        fail(f"release asset has an unexpected size: {name}: {size}")

    data = request_bytes(url, token=token, limit=MAX_ARCHIVE_BYTES)
    actual = hashlib.sha256(data).hexdigest()
    expected = digest.removeprefix("sha256:")
    if actual != expected:
        fail(f"SHA-256 mismatch for {name}: expected {expected}, got {actual}")
    destination.write_bytes(data)
    return actual


def extract_legal_metadata(archive: Path, destination: Path) -> None:
    """Extract only PYTHON.json and upstream license texts from a full archive."""
    if shutil.which("tar") is None or shutil.which("zstd") is None:
        fail("tar and zstd are required to extract Python full distributions")
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        "tar",
        "--zstd",
        "-xf",
        str(archive),
        "-C",
        str(destination),
        "python/PYTHON.json",
        "python/licenses",
    ]
    completed = subprocess.run(command, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        fail(f"cannot extract legal metadata from {archive.name}: {completed.stderr.strip()}")

    python_root = destination / "python"
    metadata = python_root / "PYTHON.json"
    licenses = python_root / "licenses"
    if not metadata.is_file() or metadata.stat().st_size == 0:
        fail(f"full distribution has no non-empty PYTHON.json: {archive.name}")
    try:
        json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"full distribution contains invalid PYTHON.json: {exc}")
    license_files = [path for path in licenses.rglob("*") if path.is_file() and path.stat().st_size]
    if not license_files:
        fail(f"full distribution has no license texts: {archive.name}")


def atomic_replace_directory(source: Path, destination: Path) -> None:
    """Replace a generated directory without exposing a partial tree."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(f".{destination.name}.old")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    source.replace(destination)
    if backup.exists():
        shutil.rmtree(backup)


def generate(root: Path, output: Path, token: str | None) -> None:
    """Download exact full distributions and preserve only their legal metadata."""
    records = parse_install_artifacts(root / "mise.lock")
    release = records[0]["release"]
    assets = list_release_assets(release, token)

    with tempfile.TemporaryDirectory(prefix="python-notices-") as temporary:
        temp_root = Path(temporary)
        generated = temp_root / "generated"
        generated.mkdir()
        manifest_records: list[dict[str, Any]] = []

        for record in records:
            asset = select_full_asset(record, assets)
            archive = temp_root / str(asset["name"])
            sha256 = download_verified_asset(asset, token, archive)
            extracted = temp_root / f"extract-{record['arch']}"
            extract_legal_metadata(archive, extracted)
            target = generated / record["arch"]
            shutil.copytree(extracted / "python", target)
            manifest_records.append(
                {
                    **record,
                    "full_asset_name": asset["name"],
                    "full_asset_url": asset["browser_download_url"],
                    "full_asset_sha256": sha256,
                    "full_asset_size": asset["size"],
                }
            )

        manifest = {
            "schema_version": 1,
            "source": "astral-sh/python-build-standalone",
            "selection_policy": list(FULL_BUILD_PREFERENCE),
            "artifacts": manifest_records,
        }
        (generated / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        atomic_replace_directory(generated, output)


def check(root: Path, output: Path) -> None:
    """Validate committed legal metadata against the current mise.lock artifacts."""
    expected_records = parse_install_artifacts(root / "mise.lock")
    manifest_path = output / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid {manifest_path}: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        fail(f"unsupported Python notice manifest: {manifest_path}")
    records = manifest.get("artifacts")
    if not isinstance(records, list):
        fail(f"Python notice manifest has no artifacts array: {manifest_path}")
    by_arch = {
        record.get("arch"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("arch"), str)
    }
    if set(by_arch) != {"amd64", "arm64"}:
        fail("Python notice manifest must contain exactly amd64 and arm64")

    for expected in expected_records:
        actual = by_arch[expected["arch"]]
        for key in ("target", "python_version", "release", "install_asset_url"):
            if actual.get(key) != expected[key]:
                fail(f"Python notice manifest mismatch for {expected['arch']} {key}")
        digest = actual.get("full_asset_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail(f"Python notice manifest has no valid digest for {expected['arch']}")
        arch_root = output / expected["arch"]
        metadata = arch_root / "PYTHON.json"
        licenses = arch_root / "licenses"
        try:
            json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"invalid committed PYTHON.json for {expected['arch']}: {exc}")
        license_files = [path for path in licenses.rglob("*") if path.is_file() and path.stat().st_size]
        if not license_files:
            fail(f"no committed Python license texts for {expected['arch']}")

    print("Python standalone runtime notices: OK")


def main() -> None:
    """Generate or validate exact Python standalone legal metadata."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    output = (
        args.output.resolve()
        if args.output
        else root / "third_party" / "components" / "python-build-standalone"
    )
    if args.write:
        generate(root, output, os.environ.get("GH_TOKEN"))
        print(f"Python standalone runtime notices written to {output}")
    else:
        check(root, output)


if __name__ == "__main__":
    main()
