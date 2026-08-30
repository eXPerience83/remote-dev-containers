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
NESTED_PARENT = {
    "name": "trzsz",
    "version": "1.1.5",
    "package_url": "https://registry.npmjs.org/trzsz/-/trzsz-1.1.5.tgz",
    "package_sha256": "a968958895e0919d4f15428f461aecb279c6979bd69b79f525c0b7ef79f17b43",
    "emitted_path": "lib/trzsz.js",
}
NESTED_COMPONENTS = {
    "base64-js": {
        "version": "1.5.1", "license": "MIT",
        "package_url": "https://registry.npmjs.org/base64-js/-/base64-js-1.5.1.tgz",
        "package_sha256": "b1b7a945b52685269083425216d6597e33d97bf21699d656e92fdb3eb5210a85",
        "license_evidence": [("base64-js/LICENSE", "5b37224c080cdcc97c871ada971c224e9926370fe74f11b539aa1cf9f3b1aca1")],
    },
    "pako": {
        "version": "2.1.0", "license": "MIT AND Zlib",
        "package_url": "https://registry.npmjs.org/pako/-/pako-2.1.0.tgz",
        "package_sha256": "49fedc8866b4abfc8e71dc7fe75ad4ef1ff1ac9601b0642cff88ee5bf2338709",
        "license_evidence": [
            ("pako/LICENSE", "a04665b3b2de56c66730c1f720f528175739e4104f79073614aa611da1e85539"),
            ("pako/ZLIB-README", "d8b499598e43d755ea8918448128259ff01820c50d94d5a48c8883d0a594ddb1"),
        ],
    },
    "ts-md5": {
        "version": "1.3.1", "license": "MIT",
        "package_url": "https://registry.npmjs.org/ts-md5/-/ts-md5-1.3.1.tgz",
        "package_sha256": "a71b284c1c1de3f3a0d73ab64dd38f6305b4c9d5ca532ed766ffbd9dcf5207ee",
        "license_evidence": [("ts-md5/LICENSE", "517d129c60daf614ba57d831f262603b2dddbee5117d93ecb45d25a4009a08d7")],
    },
    "tslib": {
        "version": "2.6.2", "license": "0BSD",
        "package_url": "https://registry.npmjs.org/tslib/-/tslib-2.6.2.tgz",
        "package_sha256": "6001e6acf1472b79a2a5044f852f282781270511b45a900850bbceac1ba8d9e2",
        "license_evidence": [
            ("tslib/LICENSE.txt", "5989359645911c04a140c49d89496b13feca980bbf36d2250a12d3b9d06250d6"),
            ("tslib/CopyrightNotice.txt", "f8b254da37e08406ccb6c9d8321ef584d1b22f44f9e12d5436325aeea0e6d60b"),
        ],
    },
}
ZMODEM_PATCH_SHA256 = "5411e786ace86f7cc14db4723f129da1c21d04852f3c32a93f7021bdc64e37aa"


def fail(message: str) -> None:
    raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def license_path(name: str) -> Path:
    return NOTICE_ROOT / name.replace("@", "_").replace("/", "_") / "LICENSE"


def validate_prebundled_components(components: dict[str, object]) -> list[dict[str, object]]:
    nested = components.get("prebundled_components")
    if not isinstance(nested, dict) or nested.get("parent") != NESTED_PARENT:
        fail("trzsz prebundled closure parent provenance does not match the exact package")
    trzsz = next((record for record in components["components"] if record["name"] == "trzsz"), None)
    if trzsz is None or trzsz.get("version") != nested["parent"]["version"]:
        fail("trzsz Webpack root and prebundled closure parent must have the same exact version")
    records = nested.get("components")
    if not isinstance(records, list) or {record.get("name") for record in records} != set(NESTED_COMPONENTS):
        fail("trzsz prebundled closure must contain exactly the known emitted components")
    for record in records:
        name = str(record["name"])
        expected = NESTED_COMPONENTS[name]
        if record.get("emitted_via") != "trzsz@1.1.5/lib/trzsz.js":
            fail(f"prebundled component {name} must identify its emitted trzsz path")
        for field in ("version", "license", "package_url", "package_sha256"):
            if record.get(field) != expected[field]:
                fail(f"prebundled component {name} {field} does not match exact evidence")
        evidence = record.get("license_evidence")
        expected_evidence = [{"path": path, "sha256": sha256} for path, sha256 in expected["license_evidence"]]
        if evidence != expected_evidence:
            fail(f"prebundled component {name} license evidence does not match")
        for item in evidence:
            path = NOTICE_ROOT / str(item["path"])
            if not path.is_file() or path.is_symlink() or digest(path) != item["sha256"]:
                fail(f"prebundled component {name} license evidence hash mismatch")
    return records


def validate_zmodem_patch(provenance: dict[str, object], components: dict[str, object]) -> None:
    patch = provenance.get("zmodem_patch")
    expected_path = "ttyd-40e79c706be14029b391f369bee6613c31667abb/html/.yarn/patches/zmodem.js-npm-0.1.10-e5537fa2ed.patch"
    if not isinstance(patch, dict) or patch.get("ttyd_commit") != provenance.get("ttyd_commit") or patch.get("upstream_path") != expected_path or patch.get("sha256") != ZMODEM_PATCH_SHA256:
        fail("zmodem patch provenance does not bind the exact ttyd source patch")
    evidence = ROOT / str(patch.get("evidence_path", ""))
    if not evidence.is_file() or evidence.is_symlink() or digest(evidence) != patch["sha256"]:
        fail("zmodem patch evidence hash mismatch")
    zmodem = next((record for record in components["components"] if record["name"] == "zmodem.js"), None)
    if zmodem is None or zmodem.get("modified_by") != {"upstream": "ttyd 1.7.7", "provenance": "provenance.json#zmodem_patch"}:
        fail("zmodem.js must record the upstream ttyd patch")


def validate_spdx(spdx: dict[str, object], records: list[dict[str, object]], provenance: dict[str, object]) -> None:
    spdx_packages = {package["name"]: package for package in spdx.get("packages", [])}
    for record in records:
        package = spdx_packages.get(record["name"])
        if package is None or package.get("versionInfo") != record["version"] or package.get("licenseDeclared") != record["license"]:
            fail(f"SPDX package mismatch for {record['name']}")
    root_package = spdx_packages.get("remote-dev-ttyd-osc52-client")
    if root_package is None or root_package.get("licenseDeclared") != "MIT AND Apache-2.0 AND Zlib AND 0BSD":
        fail("SPDX root package must represent the complete emitted license closure")
    zmodem_package = spdx_packages.get("zmodem.js")
    if zmodem_package is None or zmodem_package.get("comment") != "Modified by ttyd 1.7.7 patch recorded in provenance.json#zmodem_patch.":
        fail("SPDX zmodem.js package must identify the ttyd patch")
    if spdx.get("spdxVersion") != "SPDX-2.3" or len(spdx_packages) != len(records) + 1:
        fail("dedicated SPDX document shape is invalid")
    if not spdx.get("documentNamespace", "").endswith(provenance["generated_html_sha256"]):
        fail("SPDX namespace must identify the exact generated asset")


def expected_inventory_record(provenance: dict[str, object], components: dict[str, object]) -> dict[str, object]:
    licenses = {str(record["license"]) for record in components["components"]}
    licenses.update(str(record["license"]) for record in validate_prebundled_components(components))
    if licenses != {"MIT", "Apache-2.0", "MIT AND Zlib", "0BSD"}:
        fail("bundle component licenses must remain the exact MIT, Apache-2.0, Zlib, and 0BSD closure")
    version = str(provenance["ttyd_version"])
    return {
        "id": "remote-dev-ttyd-osc52-client",
        "name": f"Remote Dev ttyd {version} OSC 52 client asset",
        "image_scope": "both",
        "version": f"ttyd-{version}+remote-dev-osc52",
        "source": f"https://github.com/tsl0922/ttyd/tree/{provenance['ttyd_commit']}",
        "license": "MIT, Apache-2.0, Zlib, and 0BSD component terms",
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
            fail("bundle component inventory must contain 15 unique exact Webpack roots")
        for record in records:
            path = license_path(record["name"])
            if not path.is_file() or path.is_symlink() or digest(path) != record["license_sha256"]:
                fail(f"license evidence mismatch for {record['name']}")

        nested_records = validate_prebundled_components(components)
        validate_zmodem_patch(provenance, components)
        all_records = records + nested_records

        validate_spdx(spdx, all_records, provenance)

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
