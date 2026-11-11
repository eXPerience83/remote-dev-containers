#!/usr/bin/env python3
"""Verify the reviewed Playwright npm dependency lock without network access.

All published tarballs require full SHA-512 SRI from a checked-in npm lock.
Changes in the MCP pin or installed production graph fail closed until review.
"""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
EXPECTED_PATHS = {
    "", "node_modules/@playwright/mcp",
    "node_modules/playwright", "node_modules/playwright-core",
}
EXPECTED_NAME = "remote-dev-playwright-bundle"


class BadLock(ValueError):
    pass


def checked_version(versions: str) -> str:
    matches = re.findall(r"^PLAYWRIGHT_MCP_VERSION=([^\s]+)$",
                         versions, re.MULTILINE)
    if len(matches) != 1 or not re.fullmatch(r"\d+\.\d+\.\d+", matches[0]):
        raise BadLock("invalid PLAYWRIGHT_MCP_VERSION in versions.env")
    return matches[0]


def validate(package: dict, lock: dict, version: str) -> None:
    dependencies = {"@playwright/mcp": version}
    if not isinstance(package, dict) or (
        package.get("name") != EXPECTED_NAME
        or package.get("version") != "0.0.0"
        or package.get("private") is not True
        or package.get("dependencies") != dependencies
    ):
        raise BadLock("package.json does not match reviewed MCP pin")
    if lock.get("lockfileVersion") != 3:
        raise BadLock("unsupported npm lockfile format")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or set(packages) != EXPECTED_PATHS:
        raise BadLock("unexpected or missing production npm dependencies")
    root = packages[""]
    if root.get("name") != EXPECTED_NAME or root.get("version") != "0.0.0":
        raise BadLock("lockfile root identity differs from package.json")
    if root.get("dependencies") != dependencies:
        raise BadLock("lockfile root dependency differs from package.json")
    mcp = packages["node_modules/@playwright/mcp"]
    if mcp.get("version") != version:
        raise BadLock("MCP lockfile version differs from reviewed pin")
    mcp_dependencies = mcp.get("dependencies")
    if not isinstance(mcp_dependencies, dict) or set(mcp_dependencies) != {
            "playwright", "playwright-core"}:
        raise BadLock("unexpected MCP production dependency graph")
    for name, required_version in mcp_dependencies.items():
        if not isinstance(required_version, str) or not re.fullmatch(
                r"\d+\.\d+\.\d+(-[A-Za-z0-9.-]+)?", required_version):
            raise BadLock("unreviewed transitive version constraint")
        if packages["node_modules/" + name].get("version") != required_version:
            raise BadLock("resolved transitive dependency mismatch")
    for name in EXPECTED_PATHS - {""}:
        entry = packages[name]
        resolved = entry.get("resolved")
        sri = entry.get("integrity")
        if not isinstance(resolved, str) or not isinstance(sri, str):
            raise BadLock("package lacks URL or Subresource Integrity: " + name)
        parsed = urlsplit(resolved)
        if (parsed.scheme != "https" or parsed.hostname != "registry.npmjs.org"
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment or not parsed.path.endswith(".tgz")):
            raise BadLock("package tarball URL is not the trusted npm registry")
        if not sri.startswith("sha512-"):
            raise BadLock("package does not have SHA-512 SRI")
        try:
            value = base64.b64decode(sri[len("sha512-"):], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise BadLock("malformed package SRI") from exc
        if len(value) != 64:
            raise BadLock("package SHA-512 digest is not 64 bytes")


def check_repo(root: Path = REPO) -> None:
    version = checked_version((root / "versions.env").read_text())
    package = json.loads((root / "config/playwright-package.json").read_text())
    lock = json.loads((root / "config/playwright-package-lock.json").read_text())
    validate(package, lock, version)


if __name__ == "__main__":
    try:
        check_repo()
    except (BadLock, OSError, ValueError) as error:
        raise SystemExit(f"Playwright npm lock validation failed: {error}")
    print("Reviewed Playwright npm package graph and SHA-512 integrity: OK")
