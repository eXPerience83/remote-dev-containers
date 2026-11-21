#!/usr/bin/env python3
"""Offline, fail-closed stable publication wiring and ordering regressions."""

import json
import re
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STABLE = ROOT / ".github/workflows/publish-amd64.yml"
HELPER = ROOT / "scripts/validate-edge-publication-candidate.sh"
GATE = ROOT / "scripts/enforce-trivy-gate.sh"


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)


def step(source: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    check(source.count(marker) == 1, f"missing/duplicated step: {name}")
    start = source.index(marker)
    end = source.find("\n      - ", start + len(marker))
    return source[start:] if end == -1 else source[start:end]


def validate(source: str, helper: str) -> None:
    stages = [
        "Build untagged stable base candidate",
        "Resolve exact stable base AMD64 manifest",
        "Build untagged stable Remote Dev candidate",
        "Resolve exact stable Remote Dev AMD64 manifest",
        "Smoke-test the exact stable publication candidates",
        "Generate exact stable base SPDX SBOM",
        "Generate exact stable Remote Dev SPDX SBOM",
        "Record exact Chromium identity and notices in stable SPDX images",
        "Scan exact stable base candidate for critical vulnerabilities",
        "Scan exact stable Remote Dev candidate for critical vulnerabilities",
        "Enforce no fixable critical vulnerabilities",
        "Guard stable promotion against overwrite or downgrade",
        "Promote one scanned digest to canonical stable tags",
    ]
    offsets = [source.find("      - name: " + name + "\n") for name in stages]
    check(all(offset >= 0 for offset in offsets) and offsets == sorted(offsets),
          "stable promotion is missing a preceding candidate gate")
    for name in stages[:-1]:
        block = step(source, name)
        check(not re.search(r"(?m)^        (if|continue-on-error):", block),
              "mandatory stable security step conditionally skipped: " + name)
    gate = step(source, "Enforce no fixable critical vulnerabilities")
    check("run: |" in gate and
          'bash scripts/enforce-trivy-gate.sh \\' in gate and
          '"--expect-image=$BASE_MANIFEST_REF"' in gate and
          '"--expect-image=$REMOTE_DEV_MANIFEST_REF"' in gate and
          '"--expect-ubuntu=$UBUNTU_VERSION"' in gate and
          'BASE_MANIFEST_REF: ${{ steps.base_manifest.outputs.ref }}' in gate and
          'REMOTE_DEV_MANIFEST_REF: ${{ steps.runtime_manifest.outputs.ref }}' in gate and
          '"exact stable base publication candidate:trivy-publish-base.json"' in gate and
          '"exact stable Remote Dev publication candidate:trivy-publish-remote-dev.json"' in gate,
          "fixable-critical gate must execute against both exact stable candidate reports")
    check('echo "python_315_version=$PYTHON_315_VERSION"' in step(source, "Load versions"),
          "stable Python 3.15 metadata omitted")
    check("PYTHON_315_VERSION=" + "${{ steps.versions.outputs.python_315_version }}" in
          step(source, stages[0]), "stable Python 3.15 build pin omitted")
    check("BASE_IMAGE=" + "${{ steps.base_manifest.outputs.ref }}" in
          step(source, stages[2]), "runtime is not built from exact AMD64 manifest")
    smoke = step(source, stages[4])
    for token in ("bash scripts/validate-edge-publication-candidate.sh",
                  '"$BASE_MANIFEST_REF"', '"$REMOTE_DEV_MANIFEST_REF"',
                  '"$GITHUB_SHA"', '"$PROJECT_VERSION"'):
        check(token in smoke, "missing exact-candidate smoke binding: " + token)
    for name, ref in zip((stages[5], stages[6], stages[8], stages[9]),
                         ("base_manifest", "runtime_manifest",
                          "base_manifest", "runtime_manifest")):
        check("image-ref: ${{ steps." + ref + ".outputs.ref }}" in step(source, name),
              "non-exact manifest scanned: " + name)
    chromium = step(source, "Record exact Chromium identity and notices in stable SPDX images")
    check("run: |" in chromium and "set -euo pipefail" in chromium and
          chromium.count("python3 scripts/chromium-sbom-evidence.py") == 2,
          "Chromium provenance must execute on both published manifests")
    for ref, sbom, evidence in (
        ("base_manifest", "sbom-publish-base.spdx.json",
         "chromium-evidence-publish-base.json"),
        ("runtime_manifest", "sbom-publish-remote-dev.spdx.json",
         "chromium-evidence-publish-remote-dev.json"),
    ):
        check("MANIFEST_REF: ${{ steps." + ref + ".outputs.ref }}" in chromium and
              "--spdx " + sbom in chromium and "--evidence " + evidence in chromium and
              ('--image "$BASE_MANIFEST_REF"' if ref == "base_manifest" else
               '--image "$REMOTE_DEV_MANIFEST_REF"') in chromium,
              "Chromium evidence is missing an exact image or SPDX binding")
    for token in ("sbom-publish-base.spdx.json", "sbom-publish-remote-dev.spdx.json",
                  "chromium-evidence-publish-base.json",
                  "chromium-evidence-publish-remote-dev.json",
                  "trivy-publish-base.json", "trivy-publish-remote-dev.json"):
        check(token in step(source, "Upload exact stable publication evidence"),
              "missing retained evidence: " + token)
    check("expected_channel=stable" in helper and
          'io.github.experience83.remote-dev.channel "$expected_channel"' in helper and
          'elif [[ "$expected_version" =~ ^v(0|[1-9][0-9]*)' in helper,
          "candidate smoke helper fails to bind stable channel/version")
    guard = step(source, "Guard stable promotion against overwrite or downgrade")
    check("run: |" in guard and "python3 scripts/guard-stable-promotion.py" in guard and
          "--journal stable-promotion-preflight.json" in guard and
          "id: promotion_guard" in guard and
          'BASE_MANIFEST_INDEX: ${{ steps.base.outputs.digest }}' in guard and
          'REMOTE_DEV_MANIFEST_INDEX: ${{ steps.runtime.outputs.digest }}' in guard,
          "stable registry downgrade/overwrite guard omitted or misbound")
    promotion = step(source, stages[-1])
    check("if: steps.promotion_guard.outputs.mode == 'fresh'" in promotion,
          "idempotent rerun must not write stable registry tags")
    check('for tag in "$GITHUB_REF_NAME" stable stable-amd64 latest; do' in promotion,
          "stable runtime alias registry verification missing")
    check(0 <= promotion.find('promoted_base="$(jq -r') <
          promotion.find('--metadata-file runtime-promotion.json') and
          0 <= promotion.find('for tag in "$GITHUB_REF_NAME" stable-amd64; do') <
          promotion.find('--metadata-file runtime-promotion.json'),
          "base digest and aliases must be checked before runtime tag writes")
    check('for tag in "$GITHUB_REF_NAME" stable-amd64; do' in promotion and
          'tag_ref="ghcr.io/${NAMESPACE}/remote-dev-base:${tag}"' in promotion and
          'if [[ "$actual_digest" != "$BASE_DIGEST" ]]; then' in promotion,
          "stable base alias registry read-back missing")


def test_real_trivy_report_gate() -> None:
    """Run the real gate and reject cross-image, missing-coverage and malformed scans."""
    base = "ghcr.io/experience83/remote-dev-base@sha256:" + "a" * 64
    runtime = "ghcr.io/experience83/remote-dev@sha256:" + "b" * 64
    os_result = {"Target": "ubuntu:26.04", "Class": "os-pkgs", "Type": "ubuntu",
                 "Vulnerabilities": []}
    lang_result = {"Target": "node_modules", "Class": "lang-pkgs", "Type": "npm",
                   "Vulnerabilities": []}
    clean = {
        "SchemaVersion": 2, "ArtifactName": base, "ArtifactType": "container_image",
        "Metadata": {"OS": {"Family": "ubuntu", "Name": "26.04"},
                     "RepoDigests": [base]},
        "Results": [os_result, lang_result],
    }
    vulnerability = {"Severity": "CRITICAL", "FixedVersion": "2.0",
                     "PkgName": "sample", "VulnerabilityID": "CVE-SYNTHETIC-1",
                     "InstalledVersion": "1.0"}
    critical = {**clean, "Results": [
        {**os_result, "Vulnerabilities": [vulnerability]}, lang_result]}
    no_fix = json.loads(json.dumps(critical))
    no_fix["Results"][0]["Vulnerabilities"][0]["FixedVersion"] = ""
    cases = (
        ("empty placeholder", {}, False, base),
        ("wrong artifact type", {**clean, "ArtifactType": "filesystem"}, False, base),
        ("cross-image substitution", clean, False, runtime),
        ("wrong RepoDigests", {**clean, "Metadata": {"OS": clean["Metadata"]["OS"],
                                                      "RepoDigests": [runtime]}}, False, base),
        ("empty Results", {**clean, "Results": []}, False, base),
        ("missing Results", {k: v for k, v in clean.items() if k != "Results"}, False, base),
        ("missing OS coverage", {**clean, "Results": [lang_result]}, False, base),
        ("missing language coverage", {**clean, "Results": [os_result]}, False, base),
        ("empty scan result", {**clean, "Results": [{}, lang_result]}, False, base),
        ("bad severity", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{**vulnerability, "Severity": ""}]},
            lang_result]}, False, base),
        ("untyped vulnerability", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{"FixedVersion": "2.0"}]},
            lang_result]}, False, base),
        ("invalid vulnerability array", {**clean, "Results": [
            {**os_result, "Vulnerabilities": {}}, lang_result]}, False, base),
        ("wrong OS", {**clean, "Metadata": {"OS": {"Family": "debian", "Name": "13"},
                                            "RepoDigests": [base]}}, False, base),
        ("clean report", clean, True, base),
        ("fixable critical", critical, False, base),
        ("critical without known fix", no_fix, True, base),
    )
    with tempfile.TemporaryDirectory(prefix="remote-dev-trivy-gate-") as directory:
        for label, report, allowed, expected in cases:
            path = Path(directory) / (label.replace(" ", "-") + ".json")
            path.write_text(json.dumps(report), encoding="utf-8")
            cmd = ["bash", str(GATE), "--expect-image=" + expected,
                   "--expect-ubuntu=26.04", "synthetic:" + str(path)]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=15, check=False)
            check((result.returncode == 0) == allowed,
                  "Trivy gate misclassified " + label + ": " +
                  (result.stdout + result.stderr)[-450:])


def move_base_registry_check_after_runtime(workflow: str) -> str:
    """Actually reorder the base tag read-back beyond the first runtime write."""
    block = step(workflow, "Promote one scanned digest to canonical stable tags")
    start = block.index("          # Check the registry aliases")
    end = block.index("          docker buildx imagetools create", start)
    moved = block[start:end]
    return workflow.replace(block, block[:start] + block[end:] + moved)


def main() -> None:
    wf = STABLE.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    validate(wf, helper)
    test_real_trivy_report_gate()
    mutations = (
        ("omit smoke", wf.replace("      - name: Smoke-test the exact stable publication candidates\n",
                                   "      - name: Skip smoke\n", 1), helper),
        ("empty critical gate", wf.replace(
            'bash scripts/enforce-trivy-gate.sh \\',
            'true # disabled critical gate', 1), helper),
        ("wrong base binding", wf.replace("BASE_IMAGE=${{ steps.base_manifest.outputs.ref }}",
                                          "BASE_IMAGE=${{ steps.base.outputs.digest }}", 1), helper),
        ("wrong SPDX", wf.replace("image-ref: ${{ steps.runtime_manifest.outputs.ref }}",
                                  "image-ref: ${{ steps.runtime.outputs.digest }}", 1), helper),
        ("missing Chromium identity", wf.replace(
            "python3 scripts/chromium-sbom-evidence.py",
            "echo # skipped provenance", 1), helper),
        ("wrong Chromium digest", wf.replace(
            "Record exact Chromium identity and notices in stable SPDX images\n        env:\n          BASE_MANIFEST_REF: ${{ steps.base_manifest.outputs.ref }}",
            "Record exact Chromium identity and notices in stable SPDX images\n        env:\n          BASE_MANIFEST_REF: ${{ steps.base.outputs.digest }}", 1), helper),
        ("base alias verification moved after runtime tags",
         move_base_registry_check_after_runtime(wf), helper),
        ("skip smoke by condition", wf.replace(
            "      - name: Smoke-test the exact stable publication candidates\n",
            "      - name: Smoke-test the exact stable publication candidates\n        if: false\n", 1), helper),
        ("skip gate by condition", wf.replace(
            "      - name: Enforce no fixable critical vulnerabilities\n",
            "      - name: Enforce no fixable critical vulnerabilities\n        if: false\n", 1), helper),
        ("ignore gate error", wf.replace(
            "      - name: Enforce no fixable critical vulnerabilities\n",
            "      - name: Enforce no fixable critical vulnerabilities\n        continue-on-error: true\n", 1), helper),
        ("missing guard", wf.replace(
            "      - name: Guard stable promotion against overwrite or downgrade\n",
            "      - name: Skip stable promotion guard\n", 1), helper),
        ("no stable base tag read-back", wf.replace(
            'for tag in "$GITHUB_REF_NAME" stable-amd64; do',
            'for tag in "disabled-base"; do', 1), helper),
        ("channel not checked", wf, helper.replace(
            'io.github.experience83.remote-dev.channel "$expected_channel"',
            "io.github.experience83.remote-dev.channel edge", 1)),
    )
    for label, mutated, altered in mutations:
        try:
            validate(mutated, altered)
        except AssertionError:
            continue
        raise AssertionError("false PASS with " + label)
    print("Stable publication candidate/security gate tests: OK")


if __name__ == "__main__":
    main()
