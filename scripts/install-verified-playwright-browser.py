#!/usr/bin/env python3
"""Install SHA-256-pinned Playwright browser archives before any extraction.

Only run during image build. The pinned package lock and committed digest
manifest are independently validated; neither the CLI nor this tool downloads
a browser at agent startup.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

BUNDLE = Path("/opt/remote-dev/playwright")
MANIFEST = Path("/usr/share/remote-dev/browser-archives.json")
EXPECTED = ("chromium-headless-shell", "ffmpeg")
ARCH_MACHINE = {"amd64": "x86_64", "arm64": "aarch64"}
MAX_ARCHIVE_BYTES = 600_000_000
MAX_UNPACKED_BYTES = 1_500_000_000


class InvalidBrowserArchive(Exception):
    """A downloaded archive or pinned metadata violated our image contract."""


def _check(value: bool, description: str) -> None:
    if not value:
        raise InvalidBrowserArchive(description)


def _metadata_blocks(output: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for part in re.split(r"\n\s*\n", output.strip()):
        lines = part.splitlines()
        if not lines:
            continue
        title = lines[0]
        name = ("chromium-headless-shell" if title.startswith("Chrome Headless Shell ")
                else "ffmpeg" if title.startswith("FFmpeg ") else None)
        _check(name is not None and name not in result, "unexpected Playwright dry-run entry")
        urls = re.findall(r"^\s*Download url:\s*(https://\S+)\s*$", part, re.M)
        locations = re.findall(r"^\s*Install location:\s*(\S+)\s*$", part, re.M)
        _check(len(urls) == len(locations) == 1, "ambiguous Playwright download metadata")
        result[name] = {"url": urls[0], "location": locations[0]}
    _check(set(result) == set(EXPECTED), "Playwright added or removed a downloaded binary")
    return result


def validate_selection(
    manifest: dict, browsers: dict, package_version: str, arch: str,
    dry_run: str, browser_root: Path,
) -> dict[str, dict]:
    """Select exact audited downloads; reject drift in URL, revision or digest."""
    _check(arch in ARCH_MACHINE, "unsupported TARGETARCH")
    _check(manifest.get("schema_version") == 1, "unknown browser digest schema")
    _check(manifest.get("playwright_core_version") == package_version,
           "Playwright package version changed without new browser review")
    _check(set(manifest.get("archives", {})) == set(ARCH_MACHINE),
           "missing architecture-specific digest inventory")
    expected_archives = manifest["archives"][arch]
    _check(set(expected_archives) == set(EXPECTED), "incomplete downloaded payload inventory")
    source_items = {item["name"]: item for item in browsers.get("browsers", [])}
    _check(all(name in source_items for name in EXPECTED), "upstream browser manifest incomplete")
    actual = _metadata_blocks(dry_run)
    for name in EXPECTED:
        entry = expected_archives[name]
        descriptor = source_items[name]
        _check(entry.get("revision") == descriptor.get("revision"),
               "browser revision changed: " + name)
        _check(entry.get("browserVersion") == descriptor.get("browserVersion"),
               "browser version changed: " + name)
        sha = entry.get("sha256", "")
        _check(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) is not None,
               "missing or malformed reviewed SHA-256")
        url = entry.get("url", "")
        _check(isinstance(url, str) and url == actual[name]["url"],
               "Playwright download URL changed: " + name)
        parsed = urlsplit(url)
        _check(parsed.scheme == "https" and parsed.hostname == "cdn.playwright.dev"
               and not parsed.username and not parsed.password and not parsed.query
               and not parsed.fragment, "untrusted browser archive source")
        dirname = name.replace("-", "_") + "-" + entry["revision"]
        target = browser_root / dirname
        _check(actual[name]["location"] == str(target),
               "Playwright installation path changed: " + name)
        executable = entry.get("executable")
        _check(isinstance(executable, str) and
               executable == (
                   ("chrome-headless-shell-linux64/chrome-headless-shell"
                    if arch == "amd64" else
                    "chrome-headless-shell-linux-arm64/chrome-headless-shell")
                   if name == "chromium-headless-shell" else "ffmpeg-linux"),
               "unexpected browser archive executable path")
    return expected_archives


def verify_sha256(archive: Path, expected: str) -> None:
    """Verify every downloaded byte using the committed digest."""
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    _check(digest.hexdigest() == expected,
           "SHA-256 mismatch: refusing to extract browser archive")


def extract_verified_zip(archive: Path, destination: Path, executable: str) -> None:
    """Extract only safe, regular ZIP files into a fresh directory."""
    destination.mkdir(mode=0o755)
    seen: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        _check(1 <= len(infos) <= 20_000, "unexpected browser ZIP entry count")
        for item in infos:
            name = item.filename.rstrip("/")
            path = PurePosixPath(name)
            _check(bool(name) and not path.is_absolute() and
                   ".." not in path.parts and "\\" not in name and
                   "\x00" not in name and name not in seen,
                   "unsafe browser ZIP member path")
            seen.add(name)
            total += item.file_size
            _check(total <= MAX_UNPACKED_BYTES, "browser ZIP expands beyond limit")
            kind = stat.S_IFMT(item.external_attr >> 16)
            _check(kind in (0, stat.S_IFREG, stat.S_IFDIR),
                   "browser ZIP includes a symlink or special file")
            target = destination.joinpath(*path.parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            _check(not target.exists(), "browser ZIP overwrites another member")
            with z.open(item, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            is_executable = bool((item.external_attr >> 16) & 0o111)
            target.chmod(0o755 if is_executable else 0o644)
    binary = destination / executable
    _check(binary.is_file() and not binary.is_symlink(),
           "reviewed executable is absent from browser archive")
    binary.chmod(0o755)
    (destination / "INSTALLATION_COMPLETE").write_bytes(b"")


def install_one(root: Path, name: str, entry: dict) -> None:
    """Download to private scratch, verify SHA-256, then publish extracted files."""
    dirname = name.replace("-", "_") + "-" + entry["revision"]
    target = root / dirname
    _check(not target.exists() and not target.is_symlink(),
           "preexisting browser installation requires manual review")
    scratch = Path(tempfile.mkdtemp(dir=root, prefix=".verified-playwright-"))
    try:
        archive = scratch / "payload.zip"
        helper = Path(__file__).with_name("playwright_archive_download.py")
        spec = importlib.util.spec_from_file_location("playwright_archive_download", helper)
        _check(spec is not None and spec.loader is not None,
               "missing shared archive download policy")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.download_archive(entry["url"], archive, name)
        verify_sha256(archive, entry["sha256"])
        content = scratch / "unpacked"
        extract_verified_zip(archive, content, entry["executable"])
        content.rename(target)
        print("Verified browser archive installed:", name, entry["revision"],
              entry["sha256"], flush=True)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    """Verify pinned manifests, native arch and downloads before extraction."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=tuple(ARCH_MACHINE), required=True)
    args = parser.parse_args()
    _check(platform.machine().lower() == ARCH_MACHINE[args.arch],
           "TARGETARCH does not match running architecture")
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    _check(root.is_absolute() and str(root) == "/opt/remote-dev/playwright-browsers",
           "untrusted browser installation root")
    _check(root.is_dir() and not root.is_symlink(),
           "missing browser installation directory")
    installed_core = BUNDLE / "node_modules/playwright-core"
    manifest = json.loads(MANIFEST.read_text())
    package_version = json.loads((installed_core / "package.json").read_text())["version"]
    browser_metadata = json.loads((installed_core / "browsers.json").read_text())
    command = [str(BUNDLE / "node_modules/.bin/playwright"),
               "install", "--dry-run", "--only-shell", "chromium"]
    metadata = subprocess.run(command, check=True, capture_output=True,
                              text=True, timeout=60).stdout
    selection = validate_selection(manifest, browser_metadata, package_version,
                                   args.arch, metadata, root)
    for name in EXPECTED:
        install_one(root, name, selection[name])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InvalidBrowserArchive, OSError, ValueError, subprocess.SubprocessError) as exc:
        print("ERROR: verified Playwright installation refused: " + str(exc),
              file=sys.stderr)
        raise SystemExit(1) from None
