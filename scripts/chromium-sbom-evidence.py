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

def sha(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
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
binary_sha1, notice_sha1 = sha(exe, "sha1"), sha(notice, "sha1")
if license_digest != notice_digest:
    raise SystemExit("bundled Chromium notice differs from installed ZIP license")
print(json.dumps({"arch": arch, "manifest": manifest,
                  "executable": str(exe), "executable_sha256": binary_digest,
                  "executable_sha1": binary_sha1,
                  "license_file": str(license_file), "license_sha256": license_digest,
                  "installed_notice": str(notice), "notice_sha256": notice_digest,
                  "notice_sha1": notice_sha1}))
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
    for key in ("executable_sha1", "notice_sha1"):
        digest = evidence.get(key)
        demand(isinstance(digest, str) and len(digest) == 40 and
               all(c in "0123456789abcdef" for c in digest),
               "invalid image-derived SHA-1: " + key)
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
    for file_id, path, digest, sha1 in (
        (EXEC_ID, exe, evidence["executable_sha256"], evidence["executable_sha1"]),
        (LICENSE_ID, NOTICE, evidence["notice_sha256"], evidence["notice_sha1"]),
    ):
        files.append({
            "SPDXID": file_id,
            "fileName": path,
            "checksums": [{"algorithm": "SHA1", "checksumValue": sha1},
                          {"algorithm": "SHA256", "checksumValue": digest}],
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


def validate_supplemental_spdx(sbom: dict) -> None:
    """Semantically verify the Chromium additions in the final SPDX 2.3 JSON."""
    demand(sbom.get("spdxVersion") == "SPDX-2.3", "wrong SPDX document version")
    packages = [p for p in sbom.get("packages", [])
                if p.get("SPDXID") == PACKAGE_ID]
    demand(len(packages) == 1, "Chromium package must appear exactly once")
    demand(packages[0].get("filesAnalyzed") is False,
           "supplemental Chromium package must not claim full file inventory")
    files = sbom.get("files", [])
    for file_id in (EXEC_ID, LICENSE_ID):
        matches = [f for f in files if f.get("SPDXID") == file_id]
        demand(len(matches) == 1, "missing or duplicate Chromium SPDX file: " + file_id)
        checksums = matches[0].get("checksums")
        demand(isinstance(checksums, list), "SPDX file missing checksum records")
        for algorithm, size in (("SHA1", 40), ("SHA256", 64)):
            records = [c for c in checksums
                       if isinstance(c, dict) and c.get("algorithm") == algorithm]
            demand(len(records) == 1, "SPDX 2.3 file requires one " + algorithm)
            digest = records[0].get("checksumValue")
            demand(isinstance(digest, str) and len(digest) == size and
                   all(ch in "0123456789abcdef" for ch in digest),
                   "malformed SPDX " + algorithm + " checksum")
        relationships = sbom.get("relationships", [])
        demand(any(rel.get("spdxElementId") == sbom.get("SPDXID") and
                   rel.get("relatedSpdxElement") == file_id and
                   rel.get("relationshipType") == "DESCRIBES"
                   for rel in relationships), "SPDX file is not described by the document")


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
    validate_supplemental_spdx(result)
    args.spdx.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    args.evidence.write_text(json.dumps({
        "schema_version": 1, "image": args.image, "arch": evidence["arch"],
        "browserVersion": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["browserVersion"],
        "archive_url": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["url"],
        "archive_sha256": pinned["archives"][evidence["arch"]]["chromium-headless-shell"]["sha256"],
        "executable": evidence["executable"],
        "executable_sha256": evidence["executable_sha256"],
        "executable_sha1": evidence["executable_sha1"],
        "notice_path": NOTICE, "notice_sha256": evidence["notice_sha256"],
        "notice_sha1": evidence["notice_sha1"],
        "scan_status": "supplemental SPDX identity only; not a Chromium CVE scan",
    }, indent=2) + "\n", encoding="utf-8")
    print("Chromium identity recorded in SPDX:", args.image, evidence["arch"])


if __name__ == "__main__":
    main()
