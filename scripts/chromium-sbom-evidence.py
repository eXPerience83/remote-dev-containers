#!/usr/bin/env python3
"""Add evidence-backed Chromium identity to Trivy SPDX; not a vulnerability scan.

Trivy does not recognize Playwright's raw Chromium ZIP as an OS/npm package.
Inspect the *built image* and attach a discrete SPDX package/file identity with
the pinned archive SHA-256, the actual executable SHA-256, and the complete
LICENSE.headless_shell SHA-256. Do not claim that Trivy scanned Chromium CVEs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "config/playwright-browser-archives.json"
PACKAGE_ID = "SPDXRef-Package-RemoteDevChromiumHeadlessShell"
EXEC_ID = "SPDXRef-File-RemoteDevChromiumExecutable"
LICENSE_ID = "SPDXRef-File-RemoteDevChromiumLicense"
NOTICE = "/usr/share/doc/remote-dev/third_party/runtime/chromium/LICENSE.headless_shell"

# Executed by Python installed *inside* the freshly built Docker image.
# No downloaded package code is executed by the evidence collector.
INSPECT_IMAGE = r"""
import hashlib, json, os
from pathlib import Path

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(os.uname().machine)
if not arch:
    raise SystemExit("unsupported Chromium architecture")
manifest = json.loads(Path("/usr/share/remote-dev/browser-archives.json").read_text())
entry = manifest["archives"][arch]["chromium-headless-shell"]
root = Path("/opt/remote-dev/playwright-browsers") / (
    "chromium_headless_shell-" + entry["revision"])
exe = root / entry["executable"]
license_file = exe.parent / "LICENSE.headless_shell"
notice = Path("/usr/share/doc/remote-dev/third_party/runtime/chromium/LICENSE.headless_shell")
if not exe.is_file() or not os.access(exe, os.X_OK):
    raise SystemExit("pinned Chromium executable missing")
if not license_file.is_file() or not notice.is_file():
    raise SystemExit("exact Chromium license or bundled notice missing")
if license_file.stat().st_size < 100_000:
    raise SystemExit("Chromium archive license unexpectedly small")
binary_digest, license_digest, notice_digest = (
    sha(exe), sha(license_file), sha(notice))
if license_digest != notice_digest:
    raise SystemExit("bundled Chromium notice differs from installed ZIP license")
print(json.dumps({"arch": arch, "manifest": manifest,
                  "executable": str(exe), "executable_sha256": binary_digest,
                  "license_file": str(license_file), "license_sha256": license_digest,
                  "installed_notice": str(notice), "notice_sha256": notice_digest}))
"""

def demand(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def inspect_image(image: str) -> dict:
    inspected = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python", image,
         "-I", "-c", INSPECT_IMAGE],
        capture_output=True, text=True, timeout=90, check=True,
    )
    return json.loads(inspected.stdout)


def add_package(sbom: dict, evidence: dict, pinned: dict) -> dict:
    demand(sbom.get("spdxVersion") == "SPDX-2.3", "unexpected SPDX version")
    demand(isinstance(sbom.get("packages"), list) and
           isinstance(sbom.get("relationships"), list),
           "SPDX document lacks package/relationship lists")
    demand(isinstance(sbom.get("SPDXID"), str), "SPDX document missing identity")
    arch = evidence.get("arch")
    demand(arch in ("amd64", "arm64"), "unsupported image architecture")
    demand(evidence.get("manifest") == pinned, "built image manifest differs from pinned source")
    entry = pinned["archives"][arch]["chromium-headless-shell"]
    version, revision = entry["browserVersion"], entry["revision"]
    base = "/opt/remote-dev/playwright-browsers/chromium_headless_shell-" + revision
    exe = base + "/" + entry["executable"]
    license_file = exe.rsplit("/", 1)[0] + "/LICENSE.headless_shell"
    demand(evidence.get("executable") == exe and
           evidence.get("license_file") == license_file and
           evidence.get("installed_notice") == NOTICE,
           "browser executable or notice paths differ from pinned identity")
    for key in ("executable_sha256", "license_sha256", "notice_sha256"):
        digest = evidence.get(key)
        demand(isinstance(digest, str) and len(digest) == 64 and
               all(c in "0123456789abcdef" for c in digest),
               "invalid image-derived SHA-256: " + key)
    demand(evidence["license_sha256"] == evidence["notice_sha256"],
           "Chromium archive license and bundled notice disagree")
    existing_ids = {p["SPDXID"] for p in sbom["packages"]}
    existing_ids |= {f["SPDXID"] for f in sbom.get("files", [])}
    demand(not ({PACKAGE_ID, EXEC_ID, LICENSE_ID} & existing_ids),
           "Chromium SPDX evidence was already recorded")
    sbom["packages"].append({
        "SPDXID": PACKAGE_ID,
        "name": "chromium-headless-shell",
        "versionInfo": version,
        "downloadLocation": entry["url"],
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "checksums": [{"algorithm": "SHA256", "checksumValue": entry["sha256"]}],
        "sourceInfo": (
            "Supplemental inventory of Playwright-provisioned Chromium, "
            "revision " + revision + ", arch " + arch +
            ". Archive SHA-256 was pinned and verified before extraction. "
            "Only selected executable and license digests were inspected; "
            "this is not an exhaustive package file inventory or a Chromium vulnerability scan."
        ),
        "externalRefs": [{
            "referenceCategory": "PACKAGE-MANAGER",
            "referenceType": "purl",
            "referenceLocator": "pkg:generic/chromium-headless-shell@" + version +
                                "?arch=" + arch,
        }],
    })
    files = sbom.setdefault("files", [])
    for file_id, path, digest in (
        (EXEC_ID, exe, evidence["executable_sha256"]),
        (LICENSE_ID, NOTICE, evidence["notice_sha256"]),
    ):
        files.append({
            "SPDXID": file_id,
            "fileName": path,
            "checksums": [{"algorithm": "SHA256", "checksumValue": digest}],
            "licenseConcluded": "NOASSERTION",
            "licenseInfoInFiles": ["NOASSERTION"],
            "copyrightText": "NOASSERTION",
        })
        # A metadata-only package (filesAnalyzed=False) cannot contain files
        # under SPDX 2.3. Describe these selected image-evidence files
        # independently, without asserting package membership/completeness.
        sbom["relationships"].append({
            "spdxElementId": sbom["SPDXID"],
            "relatedSpdxElement": file_id,
            "relationshipType": "DESCRIBES",
        })
    sbom["relationships"].append({
        "spdxElementId": sbom["SPDXID"],
        "relatedSpdxElement": PACKAGE_ID,
        "relationshipType": "DESCRIBES",
    })
    sbom.setdefault("annotations", []).append({
        "annotationDate": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "annotationType": "OTHER",
        "annotator": "Tool: remote-dev-chromium-sbom-evidence",
        "comment": ("Chromium component added from verified image/ZIP provenance; "
                    "Trivy did not identify or vulnerability-scan Chromium."),
    })
    return sbom


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--spdx", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    pinned = json.loads(MANIFEST.read_text(encoding="utf-8"))
    evidence = inspect_image(args.image)
    result = add_package(
        json.loads(args.spdx.read_text(encoding="utf-8")), evidence, pinned)
    args.spdx.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.evidence.write_text(json.dumps({
        "schema_version": 1, "image": args.image, "arch": evidence["arch"],
        "browserVersion": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["browserVersion"],
        "archive_url": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["url"],
        "archive_sha256": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["sha256"],
        "executable": evidence["executable"],
        "executable_sha256": evidence["executable_sha256"],
        "notice_path": NOTICE, "notice_sha256": evidence["notice_sha256"],
        "scan_status": "supplemental SPDX identity only; not a Chromium CVE scan",
    }, indent=2) + "\n", encoding="utf-8")
    print("Chromium identity recorded in SPDX:", args.image, evidence["arch"])


if __name__ == "__main__":
    main()
