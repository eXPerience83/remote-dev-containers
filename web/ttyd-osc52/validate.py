#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NOTICE_ROOT = ROOT / "third_party" / "components" / "remote-dev-ttyd-osc52"


def fail(message: str) -> None:
    raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def license_path(name: str) -> Path:
    return NOTICE_ROOT / name.replace("@", "_").replace("/", "_") / "LICENSE"


def expected_inventory_record(provenance: dict[str, object], components: dict[str, object]) -> dict[str, object]:
    licenses = {str(record["license"]) for record in components["components"]}
    if licenses != {"MIT", "Apache-2.0"}:
        fail("bundle component licenses must remain the known MIT and Apache-2.0 terms")
    version = str(provenance["ttyd_version"])
    return {
        "id": "remote-dev-ttyd-osc52-client",
        "name": f"Remote Dev ttyd {version} OSC 52 client asset",
        "image_scope": "both",
        "version": f"ttyd-{version}+remote-dev-osc52",
        "source": f"https://github.com/tsl0922/ttyd/tree/{provenance['ttyd_commit']}",
        "license": "MIT and Apache-2.0 component terms",
        "notices": [
            {
                "path": "components/ttyd/LICENSE",
                "source": "repository",
                "reviewed_from": f"https://raw.githubusercontent.com/tsl0922/ttyd/{version}/LICENSE",
            },
            {
                "path": "components/remote-dev-ttyd-osc52/",
                "source": "repository",
                "reviewed_from": str((HERE / "bundle-components.json").relative_to(ROOT)),
            },
        ],
    }


def validate_inventory_record(inventory: dict[str, object], provenance: dict[str, object], components: dict[str, object]) -> None:
    records = [item for item in inventory["components"] if item.get("id") == "remote-dev-ttyd-osc52-client"]
    if len(records) != 1:
        fail("third-party inventory must contain exactly one OSC 52 client record")
    expected = expected_inventory_record(provenance, components)
    for field, value in expected.items():
        if records[0].get(field) != value:
            fail(f"third-party OSC 52 client inventory {field} does not match provenance/components")


def main() -> int:
    try:
        provenance = json.loads((HERE / "provenance.json").read_text())
        components = json.loads((HERE / "bundle-components.json").read_text())
        spdx = json.loads((NOTICE_ROOT / "remote-dev-ttyd-osc52.spdx.json").read_text())
        inventory = json.loads((ROOT / "third_party" / "inventory.json").read_text())

        if provenance["ttyd_version"] != "1.7.7" or provenance["compatibility_issue"] != 174:
            fail("the workaround must remain explicitly bound to ttyd 1.7.7 and #174")
        asset = HERE / "dist" / "index.html"
        if asset.stat().st_size != provenance["generated_html_size"] or digest(asset) != provenance["generated_html_sha256"]:
            fail("generated asset size/hash disagrees with provenance")
        html = asset.read_text()
        source = (HERE / "osc52-write.js").read_text()
        if html.count('<script id="remote-dev-osc52-write">') != 1 or html.count(source.rstrip()) != 1:
            fail("generated asset must contain exactly one readable OSC 52 script")

        forbidden = (
            "navigator.clipboard", "readText(", "localStorage", "sessionStorage",
            "fetch(", "XMLHttpRequest", "new WebSocket", "ClipboardAddon", "console.",
        )
        for token in forbidden:
            if token in source:
                fail(f"OSC 52 source contains forbidden surface: {token}")

        records = components.get("components", [])
        names = [record["name"] for record in records]
        if components.get("schema_version") != 1 or len(records) != 15 or len(names) != len(set(names)):
            fail("bundle component inventory must contain 15 unique exact runtime roots")
        for record in records:
            path = license_path(record["name"])
            if not path.is_file() or path.is_symlink() or digest(path) != record["license_sha256"]:
                fail(f"license evidence mismatch for {record['name']}")

        spdx_packages = {package["name"]: package for package in spdx.get("packages", [])}
        for record in records:
            package = spdx_packages.get(record["name"])
            if package is None or package.get("versionInfo") != record["version"] or package.get("licenseDeclared") != record["license"]:
                fail(f"SPDX package mismatch for {record['name']}")
        if spdx.get("spdxVersion") != "SPDX-2.3" or len(spdx_packages) != len(records) + 1:
            fail("dedicated SPDX document shape is invalid")
        if not spdx.get("documentNamespace", "").endswith(provenance["generated_html_sha256"]):
            fail("SPDX namespace must identify the exact generated asset")

        validate_inventory_record(inventory, provenance, components)

        dockerfile = (ROOT / "images" / "base" / "Dockerfile").read_text()
        launcher = (ROOT / "scripts" / "start-remote-dev-web.sh").read_text()
        tmux = (ROOT / "config" / "tmux.conf").read_text()
        if "COPY --chown=0:0 --chmod=0444 web/ttyd-osc52/dist/index.html" not in dockerfile:
            fail("Docker build must copy only the committed final client asset")
        if "--index /usr/share/remote-dev/ttyd/index.html" not in launcher:
            fail("ttyd launcher must serve the verified index")
        if re.search(r"(^|\s)set(?:-option)?\s+.*set-clipboard", tmux, re.MULTILINE):
            fail("Phase 1 must not change the tmux clipboard policy")
        print("OK ttyd OSC 52 asset, policy, notices, and SPDX contract")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
