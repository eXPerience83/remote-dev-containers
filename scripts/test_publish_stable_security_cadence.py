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


def runnable_lines(block: str, label: str) -> tuple[str, ...]:
    """Extract actual shell lines, excluding comments and sibling steps."""
    marker = "\n        run: |\n"
    check(block.count(marker) == 1, "missing/ambiguous executable run: " + label)
    lines = block.split(marker, 1)[1].splitlines()
    return tuple(line.strip() for line in lines if line.strip() and
                 not line.lstrip().startswith("#"))


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
    check(
        runnable_lines(gate, "critical gate") == (
            "set -euo pipefail",
            'bash scripts/enforce-trivy-gate.sh \\',
            '"--expect-image=$BASE_MANIFEST_REF" \\',
            '"--expect-ubuntu=$UBUNTU_VERSION" \\',
            '"exact stable base publication candidate:trivy-publish-base.json" \\',
            '"--expect-image=$REMOTE_DEV_MANIFEST_REF" \\',
            '"--expect-ubuntu=$UBUNTU_VERSION" \\',
            '"exact stable Remote Dev publication candidate:trivy-publish-remote-dev.json"',
        ) and
        'BASE_MANIFEST_REF: ${{ steps.base_manifest.outputs.ref }}' in gate and
        'REMOTE_DEV_MANIFEST_REF: ${{ steps.runtime_manifest.outputs.ref }}' in gate and
        'UBUNTU_VERSION: ${{ steps.versions.outputs.ubuntu_version }}' in gate,
        "critical gate must execute both exact candidate-bound reports",
    )
    check('echo "python_315_version=$PYTHON_315_VERSION"' in step(source, "Load versions"),
          "stable Python 3.15 metadata omitted")
    check("PYTHON_315_VERSION=" + "${{ steps.versions.outputs.python_315_version }}" in
          step(source, stages[0]), "stable Python 3.15 build pin omitted")
    check("BASE_IMAGE=" + "${{ steps.base_manifest.outputs.ref }}" in
          step(source, stages[2]), "runtime is not built from exact AMD64 manifest")
    smoke = step(source, stages[4])
    check(
        runnable_lines(smoke, "exact candidate smoke") == (
            "set -euo pipefail",
            'bash scripts/validate-edge-publication-candidate.sh \\',
            '"ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}" \\',
            '"$BASE_MANIFEST_REF" \\',
            '"ghcr.io/${NAMESPACE}/remote-dev@${REMOTE_DEV_DIGEST}" \\',
            '"$REMOTE_DEV_MANIFEST_REF" \\',
            '"$GITHUB_SHA" \\',
            '"$PROJECT_VERSION"',
        ),
        "exact-candidate smoke must really execute with all six expected arguments",
    )
    for name in (stages[8], stages[9]):
        scan = step(source, name)
        for required in ("scanners: vuln", "vuln-type: os,library",
                         "severity: CRITICAL", 'exit-code: "0"'):
            check(required in scan, "stable Trivy must scan fixable CRITICAL: " + name)
    for name, ref in zip((stages[5], stages[6], stages[8], stages[9]),
                         ("base_manifest", "runtime_manifest",
                          "base_manifest", "runtime_manifest")):
        check("image-ref: ${{ steps." + ref + ".outputs.ref }}" in step(source, name),
              "non-exact manifest scanned: " + name)
    chromium = step(source, "Record exact Chromium identity and notices in stable SPDX images")
    check(runnable_lines(chromium, "Chromium SPDX") == (
        "set -euo pipefail",
        'python3 scripts/chromium-sbom-evidence.py \\',
        '--image "$BASE_MANIFEST_REF" \\',
        "--spdx sbom-publish-base.spdx.json \\",
        "--evidence chromium-evidence-publish-base.json",
        'python3 scripts/chromium-sbom-evidence.py \\',
        '--image "$REMOTE_DEV_MANIFEST_REF" \\',
        "--spdx sbom-publish-remote-dev.spdx.json \\",
        "--evidence chromium-evidence-publish-remote-dev.json",
    ), "Chromium provenance must actually run on both exact manifests")
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
    independent = step(source, "Validate exact stable SPDX documents with independent parser")
    check(source.index("Record exact Chromium identity and notices in stable SPDX images") <
          source.index("Validate exact stable SPDX documents with independent parser") <
          source.index("Scan exact stable base candidate for critical vulnerabilities"),
          "independent SPDX semantics must precede stable vulnerability scan")
    check("        if:" not in independent and "        continue-on-error:" not in independent,
          "independent SPDX validator may not be skipped")
    check(runnable_lines(independent, "SPDX semantic validation") == (
        "set -euo pipefail",
        'python3 -m venv "$RUNNER_TEMP/remote-dev-spdx-validator"',
        '"$RUNNER_TEMP/remote-dev-spdx-validator/bin/python" -m pip install --disable-pip-version-check spdx-tools==0.8.5',
        '"$RUNNER_TEMP/remote-dev-spdx-validator/bin/pyspdxtools" -i sbom-publish-base.spdx.json',
        '"$RUNNER_TEMP/remote-dev-spdx-validator/bin/pyspdxtools" -i sbom-publish-remote-dev.spdx.json',
    ), "both final stable SPDX files must pass an independent validator")
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
    active_helper = tuple(line.strip() for line in helper.splitlines()
                          if line.strip() and not line.lstrip().startswith("#"))
    for required in (
        '"$runtime_ref" "$expected_version" "$expected_revision" "$expected_channel"',
        'bash "$root/scripts/runtime-smoke-test.sh" "$runtime_ref"',
        'bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"',
        'bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"',
    ):
        check(any(required in line for line in active_helper),
              "runtime candidate missing active mandatory check: " + required)
    guard = step(source, "Guard stable promotion against overwrite or downgrade")
    check(
        runnable_lines(guard, "stable tag protection guard") == (
            "set -euo pipefail",
            'python3 scripts/guard-stable-promotion.py \\',
            '--tag "$GITHUB_REF_NAME" \\',
            '--base "ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_MANIFEST_INDEX}" \\',
            '--runtime "ghcr.io/${NAMESPACE}/remote-dev@${REMOTE_DEV_MANIFEST_INDEX}" \\',
            "--journal stable-promotion-preflight.json",
        ) and
        "id: promotion_guard" in guard and
        'BASE_MANIFEST_INDEX: ${{ steps.base.outputs.digest }}' in guard and
        'REMOTE_DEV_MANIFEST_INDEX: ${{ steps.runtime.outputs.digest }}' in guard,
        "stable registry downgrade/overwrite guard must execute on exact indexes",
    )
    promotion = step(source, stages[-1])
    promotion_commands = runnable_lines(promotion, "stable tag promotion")
    check("exit 0" not in promotion_commands and
          sum(line == 'docker buildx imagetools create \\' for line
              in promotion_commands) == 2 and
          promotion_commands.count("set -euo pipefail") == 1,
          "promotion cannot skip writes or exit early")
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
    """Exercise the real gate with complete and truncated package inventories."""
    base = "ghcr.io/experience83/remote-dev-base@sha256:" + "a" * 64
    runtime = "ghcr.io/experience83/remote-dev@sha256:" + "b" * 64

    def entry(target: str, kind: str, klass: str, name: str) -> dict:
        return {"Target": target, "Class": klass, "Type": kind,
                "Packages": [{"Name": name}], "Vulnerabilities": []}

    os_result = entry("ubuntu:26.04", "ubuntu", "os-pkgs", "coreutils")
    node_result = entry("Node.js", "node-pkg", "lang-pkgs", "npm")
    python_result = entry("Python", "python-pkg", "lang-pkgs", "pip")
    binaries = [
        entry("opt/remote-dev/mise/installs/" + tool + "/1/" + tool,
              kind, "lang-pkgs", tool)
        for kind, tool in (("gobinary", "actionlint"), ("gobinary", "shfmt"),
                           ("rustbinary", "uv"), ("rustbinary", "uvx"),
                           ("gobinary", "yq"), ("gobinary", "pebble"),
                           ("gobinary", "gh"))
    ]
    complete = [os_result, node_result, python_result, *binaries]
    clean = {"SchemaVersion": 2, "ArtifactName": base,
             "ArtifactType": "container_image",
             "Metadata": {"OS": {"Family": "ubuntu", "Name": "26.04"},
                          "RepoDigests": [base]},
             "Results": complete}
    vuln = {"Severity": "CRITICAL", "FixedVersion": "2.0",
            "PkgName": "sample", "VulnerabilityID": "CVE-SYNTHETIC-1",
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
        ("empty scan result", {**clean, "Results": [{}, *complete[1:]]}, False, base),
        ("bad severity", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{**vuln, "Severity": ""}]},
            *complete[1:]]}, False, base),
        ("untyped vulnerability", {**clean, "Results": [
            {**os_result, "Vulnerabilities": [{"FixedVersion": "2.0"}]},
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
        ("commented-out gate", wf.replace(
            '          bash scripts/enforce-trivy-gate.sh \\',
            '          # bash scripts/enforce-trivy-gate.sh \\', 1), helper),
        ("commented-out smoke", wf.replace(
            '          bash scripts/validate-edge-publication-candidate.sh \\',
            '          # bash scripts/validate-edge-publication-candidate.sh \\', 1), helper),
        ("commented-out registry guard", wf.replace(
            '          python3 scripts/guard-stable-promotion.py \\',
            '          # python3 scripts/guard-stable-promotion.py \\', 1), helper),
        ("premature gate exit", wf.replace(
            '          bash scripts/enforce-trivy-gate.sh \\',
            '          exit 0\n          bash scripts/enforce-trivy-gate.sh \\', 1), helper),
        ("independent SPDX parser bypassed", wf.replace(
            '          "$RUNNER_TEMP/remote-dev-spdx-validator/bin/pyspdxtools" -i sbom-publish-base.spdx.json',
            '          # "$RUNNER_TEMP/remote-dev-spdx-validator/bin/pyspdxtools" -i sbom-publish-base.spdx.json', 1), helper),
        ("independent SPDX parser skipped", wf.replace(
            '      - name: Validate exact stable SPDX documents with independent parser\n',
            '      - name: Validate exact stable SPDX documents with independent parser\n        if: false\n', 1), helper),
        ("Chromium early bypass", wf.replace(
            '          python3 scripts/chromium-sbom-evidence.py \\',
            '          exit 0\n          python3 scripts/chromium-sbom-evidence.py \\', 1), helper),
        ("stable promote early bypass", wf.replace(
            '          base_ref="ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}"',
            '          exit 0\n          base_ref="ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}"', 1), helper),
        ("runtime auth disabled", wf, helper.replace(
            'bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"',
            '# bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"', 1)),
        ("runtime isolation disabled", wf, helper.replace(
            'bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"',
            '# bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"', 1)),
        ("internal channel not verified", wf, helper.replace(
            '"$runtime_ref" "$expected_version" "$expected_revision" "$expected_channel"',
            '"$runtime_ref" "$expected_version" "$expected_revision"', 1)),
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
        ("critical scan downgraded to HIGH", wf.replace(
            '          severity: CRITICAL',
            '          severity: HIGH', 1), helper),
        ("missing guard", wf.replace(
            "      - name: Guard stable promotion against overwrite or downgrade\n",
            "      - name: Skip stable promotion guard\n", 1), helper),
        ("no stable base tag read-back", wf.replace(
            'for tag in "$GITHUB_REF_NAME" stable-amd64; do',
            'for tag in "disabled-base"; do', 1), helper),
        ("self-comparing embedded identity", wf, helper.replace(
            '"$runtime_ref" "$expected_version" "$expected_revision"',
            '"$runtime_ref"', 1)),
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
