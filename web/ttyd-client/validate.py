#!/usr/bin/env python3
"""Validate the bounded source and generated-asset contract for issue #97."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source() -> None:
    provenance = json.loads((ROOT / "provenance.json").read_text())
    versions = dict(
        line.split("=", 1)
        for line in (REPO / "versions.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    if versions.get("TTYD_VERSION") != provenance["upstream"]["tag"]:
        fail("provenance ttyd tag disagrees with versions.env")
    if versions.get("NODE_VERSION") != provenance["toolchain"]["node"]:
        fail("provenance Node version disagrees with versions.env")

    expected: dict[str, str] = {}
    for line in (ROOT / "upstream.sha256").read_text().splitlines():
        digest, relative = line.split("  ", 1)
        expected[relative] = digest
    actual = {
        path.relative_to(ROOT / "upstream").as_posix(): sha256(path)
        for path in (ROOT / "upstream").rglob("*")
        if path.is_file()
    }
    if actual != expected:
        fail("vendored upstream file set or hash differs from upstream.sha256")

    patch = ROOT / provenance["patch"]["path"]
    if sha256(patch) != provenance["patch"]["sha256"]:
        fail("Remote Dev patch hash differs from provenance")
    yarn = ROOT / "tooling/yarn-3.6.3.cjs"
    if sha256(yarn) != provenance["toolchain"]["yarn_sha256"]:
        fail("vendored Yarn executable hash differs from provenance")

    package = json.loads((ROOT / "upstream/html/package.json").read_text())
    if package.get("packageManager") != "yarn@3.6.3":
        fail("unexpected upstream package manager")
    lock = (ROOT / "upstream/html/yarn.lock").read_text()
    if "__metadata:\n  version: 6" not in lock:
        fail("unexpected Yarn lock format")
    for line in lock.splitlines():
        if line.startswith("  resolution:") and not any(
            marker in line for marker in ("@npm:", "@patch:", "@workspace:", "@virtual:")
        ):
            fail("unexpected floating or non-registry lock resolution")
    for block in lock.split("\n\n"):
        if (
            "resolution:" in block
            and "linkType: hard" in block
            and "checksum:" not in block
            and not (block.startswith('"fsevents@patch:') and "conditions: os=darwin" in block)
        ):
            fail("locked registry package is missing a checksum")
    zmodem_patch = ROOT / "upstream/html/.yarn/patches/zmodem.js-npm-0.1.10-e5537fa2ed.patch"
    if "patch:zmodem.js@npm%3A0.1.10" not in lock or not zmodem_patch.is_file():
        fail("fixed zmodem patch is not locked")

    browser_package = json.loads((ROOT / "browser-tests/package.json").read_text())
    if browser_package.get("devDependencies") != {"@playwright/test": "1.62.1"}:
        fail("browser test dependency must remain exactly pinned")
    browser_lock = json.loads((ROOT / "browser-tests/package-lock.json").read_text())
    playwright = browser_lock.get("packages", {}).get("node_modules/@playwright/test", {})
    if playwright.get("version") != "1.62.1" or not playwright.get("integrity"):
        fail("browser test lock is missing the exact Playwright integrity")


def validate_asset() -> None:
    manifest = json.loads((ROOT / "asset-manifest.json").read_text())
    asset = ROOT / manifest["path"]
    data = asset.read_bytes()
    if len(data) != manifest["size"] or sha256(asset) != manifest["sha256"]:
        fail("committed ttyd client hash or size differs from its manifest")
    text = data.decode("utf-8")
    if manifest["marker"] not in text:
        fail("committed client lacks its Remote Dev marker")
    forbidden = (
        "<script src=",
        "<link rel=\"stylesheet\" href=",
        "sourceMappingURL=",
        "navigator.clipboard",
        "localStorage",
        "sessionStorage",
        "serviceWorker",
    )
    for token in forbidden:
        if token in text:
            fail(f"committed client contains forbidden runtime token: {token}")
    if len(list((ROOT / "dist").iterdir())) != 1:
        fail("frontend dist must contain only the self-contained index.html")

    components = json.loads((ROOT / "bundle-components.json").read_text())
    lock = (ROOT / "upstream/html/yarn.lock").read_text()
    stats = json.loads((ROOT / "bundle-stats.json").read_text())
    expected_names = {
        "ttyd-frontend", "@xterm/addon-canvas", "@xterm/addon-fit",
        "@xterm/addon-image", "@xterm/addon-unicode11", "@xterm/addon-web-links",
        "@xterm/addon-webgl", "@xterm/xterm", "css-loader", "crc-32", "decko", "file-saver",
        "preact", "trzsz", "whatwg-fetch", "zmodem.js",
    }
    if {item["name"] for item in components["components"]} != expected_names:
        fail("embedded component inventory differs from its fixed allowlist")
    if set(stats["emitted_package_roots"]) != expected_names - {"ttyd-frontend"}:
        fail("committed emitted-package summary differs from its fixed allowlist")
    if stats["asset"] != {"html_bytes": manifest["size"], "sha256": manifest["sha256"]}:
        fail("committed bundle stats disagree with the asset manifest")
    for item in components["components"]:
        if item["name"] == "ttyd-frontend":
            continue
        name = item["name"]
        if f'  resolution: "{name}@npm:{item["version"]}"' not in lock:
            fail(f"embedded component version is not present in the exact lock: {name}")
    notice_root = REPO / "third_party/components/remote-dev-ttyd-client"
    for item in components["components"] + components["build_only"]:
        if not (notice_root / item["notice"]).is_file():
            fail(f"missing embedded-client notice for {item['name']}")
    spdx = json.loads((notice_root / "remote-dev-ttyd-client.spdx.json").read_text())
    if spdx.get("spdxVersion") != "SPDX-2.3" or not spdx.get("packages"):
        fail("dedicated embedded-client SPDX document is invalid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-only", action="store_true")
    args = parser.parse_args()
    validate_source()
    if not args.source_only:
        validate_asset()
    print("Remote Dev ttyd client validation: OK")


if __name__ == "__main__":
    main()
