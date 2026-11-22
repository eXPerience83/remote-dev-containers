#!/usr/bin/env python3
"""Exercise the actual Trivy report gate and its compatible wrapper."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

GATE = Path(__file__).resolve().with_name("enforce-trivy-gate.sh")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_real_trivy_report_gate() -> None:
    """Exercise the real gate with complete and truncated package inventories."""
    base = "ghcr.io/experience83/remote-dev-base@sha256:" + "a" * 64
    runtime = "ghcr.io/experience83/remote-dev@sha256:" + "b" * 64

    binary_root_names = {
        "actionlint": "github.com/rhysd/actionlint",
        "shfmt": "mvdan.cc/sh/v3",
        "uv": "uv", "uvx": "uv",
        "yq": "github.com/mikefarah/yq/v4",
        "pebble": "github.com/canonical/pebble",
        "gh": "github.com/cli/cli/v2",
    }
    def entry(target: str, kind: str, klass: str, name: str) -> dict:
        return {"Target": target, "Class": klass, "Type": kind,
                "Packages": [{"Name": binary_root_names.get(name, name),
                              "Version": "1.0", "Relationship": "root"}],
                "Vulnerabilities": []}

    os_result = entry(base + " (ubuntu 26.04)", "ubuntu", "os-pkgs", "coreutils")
    node_result = entry("Node.js", "node-pkg", "lang-pkgs", "npm")
    python_result = entry("Python", "python-pkg", "lang-pkgs", "pip")
    binaries = [
        entry(target, kind, "lang-pkgs", tool)
        for kind, tool, target in (
            ("gobinary", "actionlint", "opt/remote-dev/mise/installs/actionlint/1/actionlint"),
            ("gobinary", "shfmt", "opt/remote-dev/mise/installs/shfmt/1/shfmt"),
            ("rustbinary", "uv", "opt/remote-dev/mise/installs/uv/1/uv"),
            ("rustbinary", "uvx", "opt/remote-dev/mise/installs/uv/1/uvx"),
            ("gobinary", "yq", "opt/remote-dev/mise/installs/yq/1/yq"),
            ("gobinary", "pebble", "usr/bin/pebble"),
            ("gobinary", "gh", "usr/local/bin/gh"),
        )
    ]
    complete = [os_result, node_result, python_result, *binaries]
    clean = {"SchemaVersion": 2, "ArtifactName": base,
             "ArtifactType": "container_image",
             "Metadata": {"OS": {"Family": "ubuntu", "Name": "26.04"},
                          "RepoDigests": [base]},
             "Results": complete}
    vuln = {"Severity": "CRITICAL", "FixedVersion": "2.0",
            "PkgName": "coreutils", "VulnerabilityID": "CVE-SYNTHETIC-1",
            "InstalledVersion": "1.0", "Status": "fixed"}
    critical = {**clean, "Results": [{**os_result, "Vulnerabilities": [vuln]},
                                      *complete[1:]]}
    no_fix = json.loads(json.dumps(critical))
    no_fix["Results"][0]["Vulnerabilities"][0].update(
        {"FixedVersion": "", "Status": "affected"})
    inconsistent = json.loads(json.dumps(critical))
    inconsistent["Results"][0]["Vulnerabilities"][0]["FixedVersion"] = "   "
    cases = (
        ("empty placeholder", {}, False, base),
        ("wrong artifact type", {**clean, "ArtifactType": "filesystem"}, False, base),
        ("cross-image substitution", clean, False, runtime),
        ("wrong RepoDigests", {**clean, "Metadata": {"OS": clean["Metadata"]["OS"],
                                                      "RepoDigests": [runtime]}}, False, base),
        ("empty Results", {**clean, "Results": []}, False, base),
        ("missing Results", {k: v for k, v in clean.items() if k != "Results"}, False, base),
        ("missing OS coverage", {**clean, "Results": complete[1:]}, False, base),
        ("missing language coverage", {**clean, "Results": [os_result]}, False, base),
        ("truncated real-like scan (Ubuntu Node)", {**clean,
             "Results": [os_result, node_result]}, False, base),
        ("missing package evidence", {**clean, "Results": [
            {k: v for k, v in os_result.items() if k != "Packages"},
            *complete[1:]]}, False, base),
        ("missing Go tool", {**clean, "Results": [
            x for x in complete if not x["Target"].endswith("/gh")]}, False, base),
        ("missing Rust inventory", {**clean, "Results": [
            x for x in complete if x["Type"] != "rustbinary"]}, False, base),
        ("HIGH-only truncated severity", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{**vuln, "Severity": "HIGH"}]},
            *complete[1:]]}, False, base),
        ("wrong Ubuntu target", {**clean, "Results": [
            {**os_result, "Target": "alien:v20 (ubuntu 22.04)"},
            *complete[1:]]}, False, base),
        ("missing package version", {**clean, "Results": [
            {**os_result, "Packages": [{"Name": "coreutils"}]},
            *complete[1:]]}, False, base),
        ("gh inventoried as Rust", {**clean, "Results": [
            *complete[:-1], {**complete[-1], "Type": "rustbinary",
                              "Target": "tmp/gh",
                              "Packages": [{"Name": "uv", "Version": "1.0",
                                            "Relationship": "root"}]}]}, False, base),
        ("gh wrong root library", {**clean, "Results": [
            *complete[:-1], {**complete[-1], "Packages": [
                {"Name": "uv", "Version": "1.0", "Relationship": "root"}]}]}, False, base),
        ("empty scan result", {**clean, "Results": [{}, *complete[1:]]}, False, base),
        ("bad severity", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{**vuln, "Severity": ""}]},
            *complete[1:]]}, False, base),
        ("untyped vulnerability", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{"FixedVersion": "2.0"}]},
            *complete[1:]]}, False, base),
        ("Ubuntu finding absent from inventory", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{**vuln, "PkgName": "absent",
                                                "FixedVersion": "", "Status": "affected"}]},
            *complete[1:]]}, False, base),
        ("wrong OS", {**clean, "Metadata": {"OS": {"Family": "debian", "Name": "13"},
                                            "RepoDigests": [base]}}, False, base),
        ("clean report with empty vulnerability lists", clean, True, base),
        ("fixable critical", critical, False, base),
        ("contradictory fixed status without fix", inconsistent, False, base),
        ("critical affected without fix", no_fix, True, base),
    )
    with tempfile.TemporaryDirectory(prefix="remote-dev-trivy-gate-") as directory:
        for label, report, allowed, expected in cases:
            path = Path(directory) / (label.replace(" ", "-").replace("/", "-") + ".json")
            path.write_text(json.dumps(report), encoding="utf-8")
            cmd = ["bash", str(GATE), "--expect-image=" + expected,
                   "--expect-ubuntu=26.04", "synthetic:" + str(path)]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=15, check=False)
            check((result.returncode == 0) == allowed,
                  "Trivy gate misclassified " + label + ": " +
                  (result.stdout + result.stderr)[-450:])

        path = Path(directory) / "clean.json"
        path.write_text(json.dumps(clean), encoding="utf-8")
        for image, ubuntu, diagnostic in (
            ("", "26.04", "invalid expected manifest ref"),
            (base, "", "missing expected Ubuntu release"),
        ):
            result = subprocess.run([
                sys.executable, str(GATE.with_name("validate-trivy-image-report.py")),
                str(path), "--expect-image", image, "--expect-ubuntu", ubuntu,
            ], capture_output=True, text=True, timeout=15)
            check(result.returncode != 0 and diagnostic in result.stdout,
                  "Trivy CLI failed to reject an empty option: " + diagnostic + "\n" +
                  result.stdout + result.stderr)

    with tempfile.TemporaryDirectory(prefix="remote-dev-trivy-local-") as directory:
        path = Path(directory)
        roles = ("remote-dev-base:local", "remote-dev:local")
        ids = ("sha256:" + "c" * 64, "sha256:" + "d" * 64)
        reports = []
        for image, image_id in zip(roles, ids, strict=True):
            report = path / (image.split(":")[0] + ".json")
            report.write_text(json.dumps({
                **no_fix, "ArtifactName": image,
                "Metadata": {"OS": clean["Metadata"]["OS"], "ImageID": image_id},
                "Results": [{**no_fix["Results"][0], "Target": image + " (ubuntu 26.04)"},
                            *complete[1:]],
            }), encoding="utf-8")
            reports.append(report)
        for report, image, image_id, allowed in (
            (reports[0], roles[0], ids[0], True),
            (reports[1], roles[1], ids[1], True),
            (reports[0], roles[1], ids[1], False),
            (reports[1], roles[1], ids[0], False),
        ):
            result = subprocess.run([
                sys.executable, str(GATE.with_name("validate-trivy-image-report.py")),
                str(report), "--expect-image", image, "--expect-local-id", image_id,
                "--expect-ubuntu", "26.04",
            ], capture_output=True, text=True, timeout=15)
            check((result.returncode == 0) == allowed, result.stdout + result.stderr)
        for allowed in (True, False):
            if not allowed:
                reports[1].write_text("{}", encoding="utf-8")
            result = subprocess.run(["bash", str(GATE), f"base:{reports[0]}",
                                     f"runtime:{reports[1]}"],
                                    capture_output=True, text=True, timeout=15)
            check((result.returncode == 0) == allowed, result.stdout + result.stderr)


if __name__ == "__main__":
    test_real_trivy_report_gate()
    print("PASS: Trivy reports bind to the scanned image and enforce candidate coverage")
