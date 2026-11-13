#!/usr/bin/env python3
"""Offline contract for reusing the Trivy installation in Build AMD64 (#327)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/build-amd64.yml"
PIN = "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"

# These are the existing eight invocations, including the four optional
# comparison artifacts. A skipped setup must never mean a skipped scan.
SCANS = (
    ("Generate base image SPDX SBOM", "remote-dev-base:local", "spdx-json", "sbom-base.spdx.json"),
    ("Generate Remote Dev image SPDX SBOM", "remote-dev:local", "spdx-json", "sbom-remote-dev.spdx.json"),
    ("Scan base image for critical vulnerabilities", "remote-dev-base:local", "json", "trivy-base.json"),
    ("Scan Remote Dev image for critical vulnerabilities", "remote-dev:local", "json", "trivy-remote-dev.json"),
    ("Record before base spdx-json evidence", "remote-dev-base:pr2-before", "spdx-json", "sbom-before-base.spdx.json"),
    ("Record before base json evidence", "remote-dev-base:pr2-before", "json", "trivy-before-base.json"),
    ("Record before runtime spdx-json evidence", "remote-dev:pr2-before", "spdx-json", "sbom-before-runtime.spdx.json"),
    ("Record before runtime json evidence", "remote-dev:pr2-before", "json", "trivy-before-runtime.json"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def named_steps(workflow: str) -> dict[str, str]:
    steps: dict[str, str] = {}
    # Only top-level job steps; a word found in another step's run block
    # cannot satisfy this contract.
    for segment in ("\n" + workflow).split("\n      - ")[1:]:
        header, _, body = segment.partition("\n")
        if not header.startswith("name: "):
            continue
        name = header.removeprefix("name: ")
        require(name not in steps, f"duplicate workflow step: {name}")
        steps[name] = body
    return steps


def validate(workflow: str) -> None:
    steps = named_steps(workflow)
    require(workflow.count(f"uses: {PIN}") == len(SCANS), "Trivy pin or invocation count changed")
    require(workflow.count("uses: aquasecurity/trivy-action@") == len(SCANS),
            "unexpected Trivy action/version")
    positions: list[int] = []

    for index, (name, image, format_name, output) in enumerate(SCANS):
        require(name in steps, f"missing scan: {name}")
        body = steps[name]
        require(f"uses: {PIN}" in body, f"unpinned action in {name}")
        require(f"image-ref: {image}" in body, f"image identity changed in {name}")
        require(f"format: {format_name}" in body, f"report format changed in {name}")
        require(f"output: {output}" in body, f"report output changed in {name}")
        if index == 0:
            require("skip-setup-trivy:" not in body, "first scan must install Trivy")
        else:
            require("          skip-setup-trivy: true" in body,
                    f"subsequent scan must reuse setup: {name}")
        if index >= 4:
            require("if: github.event_name == 'workflow_dispatch' && inputs.compare_images == true"
                    in body, f"optional comparison trigger changed: {name}")
            require("exit-code: '0'" in body, f"optional comparison exit code changed: {name}")
        elif index in (2, 3):
            for setting in ("scanners: vuln", "vuln-type: os,library",
                            "severity: CRITICAL", 'exit-code: "0"'):
                require(setting in body, f"critical scan setting lost in {name}: {setting}")
        positions.append(workflow.index(f"      - name: {name}\n"))

    require(positions == sorted(positions), "Trivy scan order changed")
    gate = "      - name: Enforce no fixable critical vulnerabilities\n"
    require(workflow.count(gate) == 1, "missing or duplicate critical vulnerability gate")
    require(positions[-1] < workflow.index(gate), "security gate must follow all scans")
    require("bash scripts/enforce-trivy-gate.sh" in steps["Enforce no fixable critical vulnerabilities"],
            "fixable critical vulnerability gate removed")
    require("sbom-base.spdx.json" in steps["Upload security and SBOM reports"]
            and "trivy-remote-dev.json" in steps["Upload security and SBOM reports"],
            "security artifacts must still be uploaded")


def reject_mutation(candidate: str, label: str) -> None:
    try:
        validate(candidate)
    except AssertionError:
        return
    raise AssertionError(f"contract accepted invalid workflow: {label}")


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    validate(workflow)
    first_output = "          output: sbom-base.spdx.json\n"
    require(first_output in workflow, "missing base SBOM output fixture")
    reject_mutation(
        workflow.replace(first_output, first_output + "          skip-setup-trivy: true\n", 1),
        "initial installer skipped",
    )
    later_flag = "          skip-setup-trivy: true\n"
    require(workflow.count(later_flag) == len(SCANS) - 1, "expected seven setup-reuse flags")
    reject_mutation(workflow.replace(later_flag, "", 1), "later installer omission")
    reject_mutation(workflow.replace("output: trivy-remote-dev.json",
                                     "output: altered-report.json", 1),
                    "missing runtime critical report")
    print("PASS: Build Trivy installs once and retains all eight scans, artifacts and security gate")


if __name__ == "__main__":
    main()
