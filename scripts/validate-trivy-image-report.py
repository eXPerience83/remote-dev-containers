#!/usr/bin/env python3
"""Validate a real, candidate-bound Trivy image report before the critical gate.

Fail closed on wrong or incomplete artifact identity, missing OS/language coverage,
and malformed vulnerability records. An empty Vulnerabilities list is valid only
when its enclosing scan target has a real Trivy class, type and target.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path, PurePosixPath

LOCAL_IMAGES = {"remote-dev-base:local", "remote-dev:local"}
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
DIGEST_REF = re.compile(r"^ghcr\.io/experience83/remote-dev(?:-base)?@sha256:[0-9a-f]{64}$")
# These tool binaries are included in both supported AMD64 image roles.
# Validate analyzer, installation location and root package identity together.
EXPECTED_TOOLS = {
    "actionlint": ("gobinary", "opt/remote-dev/mise/installs/actionlint/", "github.com/rhysd/actionlint"),
    "shfmt": ("gobinary", "opt/remote-dev/mise/installs/shfmt/", "mvdan.cc/sh/v3"),
    "uv": ("rustbinary", "opt/remote-dev/mise/installs/uv/", "uv"),
    "uvx": ("rustbinary", "opt/remote-dev/mise/installs/uv/", "uv"),
    "yq": ("gobinary", "opt/remote-dev/mise/installs/yq/", "github.com/mikefarah/yq/v4"),
    "pebble": ("gobinary", "usr/bin/pebble", "github.com/canonical/pebble"),
    "gh": ("gobinary", "usr/local/bin/gh", "github.com/cli/cli/v2"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def ubuntu_package_version(package: dict) -> str:
    version = package["Version"]
    if package.get("Epoch"):
        version = f'{package["Epoch"]}:{version}'
    if package.get("Release"):
        version = f'{version}-{package["Release"]}'
    return version


def validate(report: object, expected_image: str | None = None,
             ubuntu: str | None = None, local_id: str | None = None) -> tuple[int, int]:
    require(isinstance(report, dict), "Trivy report is not a JSON object")
    require(report.get("SchemaVersion") == 2, "wrong Trivy schema version")
    require(report.get("ArtifactType") == "container_image", "not an image scan")
    name = report.get("ArtifactName")
    require(isinstance(name, str) and bool(name.strip()), "missing artifact identity")
    meta = report.get("Metadata")
    require(isinstance(meta, dict), "missing image metadata")
    os_meta = meta.get("OS")
    require(isinstance(os_meta, dict) and os_meta.get("Family") == "ubuntu",
            "missing Ubuntu OS metadata")
    os_release = os_meta.get("Name")
    require(isinstance(os_release, str) and bool(os_release.strip()), "missing Ubuntu release")
    if ubuntu is not None:
        require(bool(ubuntu), "missing expected Ubuntu release")
        require(os_release == ubuntu or os_release.startswith(ubuntu + "."),
                "wrong Ubuntu release; expected " + ubuntu)
    if expected_image in LOCAL_IMAGES:
        require(local_id is not None and bool(DIGEST.fullmatch(local_id)),
                "local scan requires an expected Docker image ID")
        require(name == expected_image and meta.get("ImageID") == local_id,
                "Trivy report does not match the expected local image and ID")
    else:
        require(local_id is None, "--expect-local-id requires a known local image")
        if expected_image is not None:
            require(bool(DIGEST_REF.fullmatch(expected_image)), "invalid expected manifest ref")
            require(name == expected_image, "Trivy scanned a different image: " + name)
            digests = meta.get("RepoDigests")
            require(isinstance(digests, list) and expected_image in digests,
                    "exact candidate is missing from RepoDigests")
    results = report.get("Results")
    require(isinstance(results, list) and bool(results), "missing scan coverage: Results")
    seen: set[tuple[str, str]] = set()
    verified_tools: set[str] = set()
    fixable = 0
    unfixed = 0
    for result in results:
        require(isinstance(result, dict), "invalid scan result")
        klass = result.get("Class")
        require(klass in ("os-pkgs", "lang-pkgs"), "unexpected or missing scan class")
        require(isinstance(result.get("Target"), str) and bool(result["Target"].strip()),
                "scan result missing target")
        require(isinstance(result.get("Type"), str) and bool(result["Type"].strip()),
                "scan result missing package type")
        kind = result["Type"]
        if klass == "os-pkgs":
            require(kind == "ubuntu", "OS scan does not cover Ubuntu packages")
            expected_target = f"{name} (ubuntu {os_release})"
            require(result["Target"] == expected_target,
                    "Ubuntu scan target disagrees with candidate identity/release")
        elif kind == "node-pkg":
            require(result["Target"] == "Node.js", "unexpected Node.js scan target")
        elif kind == "python-pkg":
            require(result["Target"] == "Python", "unexpected Python scan target")
        # A class/target label alone is not evidence of successful package
        # discovery. Raw, truncated Trivy results without Packages must fail.
        packages = result.get("Packages")
        require(isinstance(packages, list) and bool(packages),
                "empty/missing package inventory for " + result["Target"])
        require(all(isinstance(p, dict) and
                    isinstance(p.get("Name"), str) and bool(p["Name"].strip()) and
                    isinstance(p.get("Version"), str) and bool(p["Version"].strip())
                    for p in packages),
                "missing name or version in package inventory: " + result["Target"])
        seen.add((klass, kind))
        if klass == "lang-pkgs" and kind in ("gobinary", "rustbinary"):
            target = result["Target"]
            basename = PurePosixPath(target).name
            if basename in EXPECTED_TOOLS:
                expected_kind, prefix, root_name = EXPECTED_TOOLS[basename]
                require(kind == expected_kind and
                        (target == prefix if prefix.startswith("usr/") else
                         target.startswith(prefix)),
                        "unexpected tool analyzer or path: " + basename)
                require(any(p.get("Name") == root_name and
                            p.get("Relationship") == "root"
                            for p in packages),
                        "tool binary lacks expected root package: " + basename)
                verified_tools.add(basename)
        ubuntu_inventory = (
            {(p["Name"], ubuntu_package_version(p)) for p in packages}
            if klass == "os-pkgs" else set()
        )
        vulnerabilities = result.get("Vulnerabilities", [])
        require(isinstance(vulnerabilities, list), "malformed vulnerability array")
        for vuln in vulnerabilities:
            require(isinstance(vuln, dict), "malformed vulnerability record")
            for field in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity"):
                value = vuln.get(field)
                require(isinstance(value, str) and bool(value.strip()),
                        "vulnerability is missing " + field)
            if klass == "os-pkgs":
                require((vuln["PkgName"], vuln["InstalledVersion"]) in ubuntu_inventory,
                        "Ubuntu finding is missing from its package inventory: " + vuln["PkgName"])
            # Workflows request only CRITICAL. A report with HIGH and no CRITICAL
            # must not be mistaken for a clean critical-only scan.
            require(vuln["Severity"] == "CRITICAL",
                    "Trivy report is not limited to CRITICAL severity")
            fixed = vuln.get("FixedVersion", "")
            require(fixed is None or isinstance(fixed, str), "invalid FixedVersion")
            status = vuln.get("Status")
            require(status is None or isinstance(status, str), "invalid Status")
            require(status != "fixed" or
                    (isinstance(fixed, str) and bool(fixed.strip())),
                    "contradictory Trivy finding: fixed status without FixedVersion")
            if isinstance(fixed, str) and fixed.strip():
                fixable += 1
                print("FIXABLE CRITICAL: " + " | ".join(
                    (vuln["VulnerabilityID"], vuln["PkgName"],
                     vuln["InstalledVersion"] + " -> " + fixed, result["Target"])))
            else:
                unfixed += 1
    # These installed tool families and binaries are present in both
    # supported AMD64 image roles; do not pin an arbitrary number of results
    # or the versions encoded in their paths.
    required = {
        ("os-pkgs", "ubuntu"),
        ("lang-pkgs", "node-pkg"),
        ("lang-pkgs", "python-pkg"),
        ("lang-pkgs", "gobinary"),
        ("lang-pkgs", "rustbinary"),
    }
    require(required <= seen,
            "incomplete Trivy scan coverage; missing types: " +
            repr(sorted(required - seen)))
    require(set(EXPECTED_TOOLS) <= verified_tools,
            "incomplete Trivy tool coverage; missing validated binaries: " +
            repr(sorted(set(EXPECTED_TOOLS) - verified_tools)))
    return fixable, unfixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--expect-image")
    parser.add_argument("--expect-ubuntu")
    parser.add_argument("--expect-local-id")
    args = parser.parse_args()
    try:
        result = json.loads(args.report.read_text(encoding="utf-8"))
        fixable, unfixed = validate(result, args.expect_image, args.expect_ubuntu, args.expect_local_id)
    except (OSError, ValueError, UnicodeError) as exc:
        print("ERROR: incomplete or invalid Trivy scan: " + str(exc))
        return 1
    print(f"Trivy report validated: fixable CRITICAL={fixable}; without fix={unfixed}")
    return 1 if fixable else 0


if __name__ == "__main__":
    raise SystemExit(main())
