#!/usr/bin/env python3
"""Offline, fail-closed stable publication wiring and ordering regressions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STABLE = ROOT / ".github/workflows/publish-amd64.yml"
HELPER = ROOT / "scripts/validate-edge-publication-candidate.sh"


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
        "Scan exact stable base candidate for critical vulnerabilities",
        "Scan exact stable Remote Dev candidate for critical vulnerabilities",
        "Enforce no fixable critical vulnerabilities",
        "Promote one scanned digest to canonical stable tags",
    ]
    offsets = [source.find("      - name: " + name + "\n") for name in stages]
    check(all(offset >= 0 for offset in offsets) and offsets == sorted(offsets),
          "stable promotion is missing a preceding candidate gate")
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
    for name, ref in zip(stages[5:9], ["base_manifest", "runtime_manifest",
                                       "base_manifest", "runtime_manifest"]):
        check("image-ref: ${{ steps." + ref + ".outputs.ref }}" in step(source, name),
              "non-exact manifest scanned: " + name)
    for token in ("sbom-publish-base.spdx.json", "sbom-publish-remote-dev.spdx.json",
                  "trivy-publish-base.json", "trivy-publish-remote-dev.json"):
        check(token in step(source, "Upload exact stable publication evidence"),
              "missing retained evidence: " + token)
    check("expected_channel=stable" in helper and
          'io.github.experience83.remote-dev.channel "$expected_channel"' in helper and
          'elif [[ "$expected_version" =~ ^v[0-9]+' in helper,
          "candidate smoke helper fails to bind stable channel/version")
    check('for tag in "$GITHUB_REF_NAME" stable stable-amd64 latest; do' in
          step(source, stages[-1]), "stable alias digest verification missing")


def main() -> None:
    wf = STABLE.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    validate(wf, helper)
    mutations = (
        ("omit smoke", wf.replace("      - name: Smoke-test the exact stable publication candidates\n",
                                   "      - name: Skip smoke\n", 1), helper),
        ("omit critical gate", wf.replace("      - name: Enforce no fixable critical vulnerabilities\n",
                                           "      - name: Skip critical gate\n", 1), helper),
        ("wrong base binding", wf.replace("BASE_IMAGE=${{ steps.base_manifest.outputs.ref }}",
                                          "BASE_IMAGE=${{ steps.base.outputs.digest }}", 1), helper),
        ("wrong SPDX", wf.replace("image-ref: ${{ steps.runtime_manifest.outputs.ref }}",
                                  "image-ref: ${{ steps.runtime.outputs.digest }}", 1), helper),
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
