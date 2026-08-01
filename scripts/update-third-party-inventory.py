#!/usr/bin/env python3
"""Synchronize the declarative legal inventory with versions.env."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NoReturn

ALLOWED_NOTICE_HOSTS = frozenset({"raw.githubusercontent.com"})
MAX_NOTICE_BYTES = 2 * 1024 * 1024
USER_AGENT = "remote-dev-containers legal inventory updater"


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error."""
    raise SystemExit(f"ERROR: {message}")


def parse_versions(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE pins without evaluating shell code."""
    versions: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")

    for number, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"{path}:{number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        if not key or not value:
            fail(f"{path}:{number}: empty key or value")
        versions[key] = value
    return versions


def load_inventory(path: Path) -> dict[str, Any]:
    """Load the JSON inventory and require its component list."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("components"), list):
        fail(f"{path} has no components array")
    return data


def validate_download_url(url: str) -> None:
    """Require an approved HTTPS host without embedded credentials."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        fail(f"repository notice URL must use HTTPS: {url}")
    if parsed.username or parsed.password:
        fail(f"repository notice URL must not contain credentials: {url}")
    if parsed.hostname.lower() not in ALLOWED_NOTICE_HOSTS:
        fail(f"repository notice URL host is not approved: {url}")


def validate_notice_url(url: str, version: str) -> None:
    """Require an approved, version-specific repository notice URL."""
    validate_download_url(url)
    if url.count(version) != 1:
        fail(f"repository notice URL must contain component version exactly once: {url}")


def derive_notice_url(url: str, old_version: str, new_version: str) -> str:
    """Replace one exact version token in a reviewed source URL."""
    validate_notice_url(url, old_version)
    updated = url.replace(old_version, new_version, 1)
    validate_notice_url(updated, new_version)
    return updated


def download_notice(url: str) -> bytes:
    """Download one bounded legal document from its approved HTTPS source."""
    validate_download_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            validate_download_url(final_url)
            content = response.read(MAX_NOTICE_BYTES + 1)
    except OSError as exc:
        fail(f"cannot download {url}: {exc}")

    if not content:
        fail(f"downloaded notice is empty: {url}")
    if len(content) > MAX_NOTICE_BYTES:
        fail(f"downloaded notice exceeds {MAX_NOTICE_BYTES} bytes: {url}")
    return content


def resolve_notice_path(root: Path, relative: str, component_id: str) -> Path:
    """Resolve a repository notice and keep it inside third_party/."""
    base = (root / "third_party").resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        fail(f"{component_id} repository notice path escapes third_party/: {relative}")
    if candidate == base:
        fail(f"{component_id} repository notice path must identify a file: {relative}")
    return candidate


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace a file atomically in its existing directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Serialize stable two-space JSON followed by a newline."""
    content = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()
    atomic_write_bytes(path, content)


def check_inventory(root: Path, inventory: dict[str, Any], versions: dict[str, str]) -> None:
    """Check version alignment and repository-document source contracts."""
    seen_keys: set[str] = set()
    for component in inventory["components"]:
        if not isinstance(component, dict):
            fail("inventory component must be an object")
        component_id = component.get("id", "<unknown>")
        key = component.get("version_key")
        if key is None:
            continue
        if not isinstance(key, str) or not key:
            fail("component version_key must be a non-empty string")
        if key in seen_keys:
            fail(f"duplicate inventory version_key: {key}")
        seen_keys.add(key)

        expected = versions.get(key)
        actual = component.get("version")
        if expected is None:
            fail(f"inventory version key is absent from versions.env: {key}")
        if actual != expected:
            fail(f"{key} is {expected} in versions.env but {actual} in the inventory")

        notices = component.get("notices")
        if not isinstance(notices, list):
            fail(f"{component_id} has no notices array")
        for notice in notices:
            if not isinstance(notice, dict) or notice.get("source") != "repository":
                continue
            relative = notice.get("path")
            url = notice.get("reviewed_from")
            if not isinstance(relative, str) or not relative:
                fail(f"{component_id} has an invalid repository notice path")
            if not isinstance(url, str) or not url:
                fail(f"{component_id} repository notice lacks reviewed_from")
            validate_notice_url(url, expected)
            notice_path = resolve_notice_path(root, relative, str(component_id))
            if not notice_path.is_file() or notice_path.stat().st_size == 0:
                fail(f"repository notice is missing or empty: {notice_path}")


def update_inventory(root: Path, inventory: dict[str, Any], versions: dict[str, str]) -> bool:
    """Refresh changed versions and their repository-preserved legal documents."""
    changed = False
    pending_files: list[tuple[Path, bytes]] = []
    seen_keys: set[str] = set()

    for component in inventory["components"]:
        if not isinstance(component, dict):
            fail("inventory component must be an object")
        component_id = component.get("id", "<unknown>")
        key = component.get("version_key")
        if key is None:
            continue
        if not isinstance(key, str) or not key:
            fail("component version_key must be a non-empty string")
        if key in seen_keys:
            fail(f"duplicate inventory version_key: {key}")
        seen_keys.add(key)

        new_version = versions.get(key)
        old_version = component.get("version")
        if new_version is None:
            fail(f"inventory version key is absent from versions.env: {key}")
        if not isinstance(old_version, str) or not old_version:
            fail(f"{component_id} has no valid version")
        if new_version == old_version:
            continue

        notices = component.get("notices")
        if not isinstance(notices, list):
            fail(f"{component_id} has no notices array")
        for notice in notices:
            if not isinstance(notice, dict) or notice.get("source") != "repository":
                continue
            relative = notice.get("path")
            old_url = notice.get("reviewed_from")
            if not isinstance(relative, str) or not relative:
                fail(f"{component_id} has an invalid repository notice path")
            if not isinstance(old_url, str) or not old_url:
                fail(f"{component_id} repository notice lacks reviewed_from")
            notice_path = resolve_notice_path(root, relative, str(component_id))
            new_url = derive_notice_url(old_url, old_version, new_version)
            pending_files.append((notice_path, download_notice(new_url)))
            notice["reviewed_from"] = new_url

        component["version"] = new_version
        changed = True

    if not changed:
        return False

    for path, content in pending_files:
        atomic_write_bytes(path, content)

    inventory["refreshed_on"] = datetime.now(timezone.utc).date().isoformat()
    atomic_write_json(root / "third_party" / "inventory.json", inventory)
    return True


def main() -> None:
    """Run deterministic checks or update changed inventory entries."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    versions = parse_versions(root / "versions.env")
    inventory = load_inventory(root / "third_party" / "inventory.json")

    if args.check:
        check_inventory(root, inventory, versions)
        print("Third-party inventory updater contract: OK")
        return

    changed = update_inventory(root, inventory, versions)
    refreshed = load_inventory(root / "third_party" / "inventory.json")
    check_inventory(root, refreshed, versions)
    if changed:
        print("Third-party inventory and repository notices refreshed for review.")
    else:
        print("Third-party inventory already current.")


if __name__ == "__main__":
    main()
