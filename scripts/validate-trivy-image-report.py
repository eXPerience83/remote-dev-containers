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
from pathlib import Path

DIGEST_REF = re.compile(r"^ghcr\.io/experience83/remote-dev(?:-base)?@sha256:[0-9a-f]{64}$")
SEVERITIES = {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate(report: object, expected_image: str | None = None, ubuntu: str | None = None) -> tuple[int, int]:
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
    if ubuntu:
        require(os_release == ubuntu or os_release.startswith(ubuntu + "."),
                "wrong Ubuntu release; expected " + ubuntu)
    if expected_image:
        require(bool(DIGEST_REF.fullmatch(expected_image)), "invalid expected manifest ref")
        require(name == expected_image, "Trivy scanned a different image: " + name)
        digests = meta.get("RepoDigests")
        require(isinstance(digests, list) and expected_image in digests,
                "exact candidate is missing from RepoDigests")
    results = report.get("Results")
    require(isinstance(results, list) and bool(results), "missing scan coverage: Results")
    seen: set[str] = set()
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
        if klass == "os-pkgs":
            require(result["Type"] == "ubuntu", "OS scan does not cover Ubuntu packages")
        seen.add(klass)
        vulnerabilities = result.get("Vulnerabilities", [])
        require(isinstance(vulnerabilities, list), "malformed vulnerability array")
        for vuln in vulnerabilities:
            require(isinstance(vuln, dict), "malformed vulnerability record")
            for field in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity"):
                value = vuln.get(field)
                require(isinstance(value, str) and bool(value.strip()),
                        "vulnerability is missing " + field)
            require(vuln["Severity"] in SEVERITIES, "unrecognized vulnerability severity")
            fixed = vuln.get("FixedVersion", "")
            require(fixed is None or isinstance(fixed, str), "invalid FixedVersion")
            if vuln["Severity"] == "CRITICAL":
                if isinstance(fixed, str) and fixed.strip():
                    fixable += 1
                    print("FIXABLE CRITICAL: " + " | ".join(
                        (vuln["VulnerabilityID"], vuln["PkgName"],
                         vuln["InstalledVersion"] + " -> " + fixed, result["Target"])))
                else:
                    unfixed += 1
    require({"os-pkgs", "lang-pkgs"} <= seen,
            "missing Trivy OS or language package scan coverage")
    return fixable, unfixed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--expect-image")
    parser.add_argument("--expect-ubuntu")
    args = parser.parse_args()
    try:
        result = json.loads(args.report.read_text(encoding="utf-8"))
        fixable, unfixed = validate(result, args.expect_image, args.expect_ubuntu)
    except (OSError, ValueError, UnicodeError) as exc:
        print("ERROR: incomplete or invalid Trivy scan: " + str(exc))
        return 1
    print(f"Trivy report validated: fixable CRITICAL={fixable}; without fix={unfixed}")
    return 1 if fixable else 0


if __name__ == "__main__":
    raise SystemExit(main())
