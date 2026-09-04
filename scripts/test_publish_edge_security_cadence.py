#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/publish-edge-amd64.yml"
HELPER = ROOT / "scripts/validate-edge-publication-candidate.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(text: str, needle: str, label: str) -> None:
    require(needle in text, f"missing {label}: {needle}")


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")

    require_text(workflow, 'cron: "11 1 * * 0"', "weekly Sunday security rebuild")
    require_text(workflow, "workflow_dispatch:", "manual rebuild dispatch")
    require_text(workflow, "push:\n    branches:\n      - main", "normal main publication trigger")
    require("pull_request:" not in workflow, "publisher must never run from pull_request")
    require_text(workflow, "permissions:\n  contents: read", "read-only workflow default")
    require(workflow.count("packages: write") == 1, "packages:write must exist exactly once")
    require_text(
        workflow,
        "publish-edge:\n    runs-on: ubuntu-latest\n    timeout-minutes: 120\n    permissions:\n      contents: read\n      packages: write",
        "package write limited to publication job",
    )
    require_text(workflow, "Require the main branch", "main branch execution guard")
    require_text(workflow, "persist-credentials: false", "credential-free checkout")

    helper_step = workflow.index("Smoke-test the exact publication candidates")
    base_sbom = workflow.index("Generate exact edge base SPDX SBOM")
    runtime_sbom = workflow.index("Generate exact edge Remote Dev SPDX SBOM")
    base_scan = workflow.index("Scan exact edge base candidate for critical vulnerabilities")
    runtime_scan = workflow.index("Scan exact edge Remote Dev candidate for critical vulnerabilities")
    gate = workflow.index("Enforce no fixable critical vulnerabilities")
    promote = workflow.index("Promote one scanned and smoke-tested digest to canonical edge tags")
    require(
        helper_step < base_sbom < runtime_sbom < base_scan < runtime_scan < gate < promote,
        "candidate smoke, SPDX, Trivy and gate must all precede promotion",
    )

    require_text(
        workflow,
        '"ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}"',
        "exact base candidate helper reference",
    )
    require_text(
        workflow,
        '"ghcr.io/${NAMESPACE}/remote-dev@${REMOTE_DEV_DIGEST}"',
        "exact runtime candidate helper reference",
    )
    require_text(workflow, "sbom-publish-base.spdx.json", "base SPDX artifact")
    require_text(workflow, "sbom-publish-remote-dev.spdx.json", "runtime SPDX artifact")
    require_text(workflow, "trivy-publish-base.json", "base Trivy report")
    require_text(workflow, "trivy-publish-remote-dev.json", "runtime Trivy report")
    require_text(workflow, "retention-days: 14", "bounded publication evidence")
    require_text(workflow, "scripts/enforce-trivy-gate.sh", "shared fixable-critical gate")

    require_text(
        workflow,
        '--tag "ghcr.io/${NAMESPACE}/remote-dev-base:edge-amd64"',
        "base edge tag",
    )
    require_text(workflow, '--tag "ghcr.io/${NAMESPACE}/remote-dev:edge"', "runtime edge tag")
    require_text(
        workflow,
        '--tag "ghcr.io/${NAMESPACE}/remote-dev:edge-amd64"',
        "runtime edge-amd64 tag",
    )
    require_text(workflow, "actual_base_digest", "base promotion verification")
    require_text(workflow, 'for tag in edge edge-amd64 "sha-${GITHUB_SHA}"', "runtime tag verification")

    lowered = workflow.lower()
    for forbidden in (
        ":stable",
        ":latest",
        "stable-amd64",
        "latest =",
        "pull_request_target",
    ):
        require(forbidden not in lowered, f"forbidden surface in edge publisher: {forbidden}")

    require_text(
        helper,
        "^ghcr\\.io/experience83/remote-dev-base@sha256:[0-9a-f]{64}$",
        "helper canonical base digest restriction",
    )
    require_text(
        helper,
        "^ghcr\\.io/experience83/remote-dev@sha256:[0-9a-f]{64}$",
        "helper canonical runtime digest restriction",
    )
    require_text(helper, "{{.Os}}/{{.Architecture}}", "linux/amd64 platform inspection")
    require_text(helper, "org.opencontainers.image.revision", "source revision label check")
    require_text(helper, "org.opencontainers.image.version", "edge version label check")
    require_text(helper, "io.github.experience83.remote-dev.channel", "channel label check")

    require_text(helper, "runtime_image_id=", "pulled runtime image-ID resolution")
    require_text(helper, '"$runtime_image_id" >/dev/null', "strict fixture uses pulled image ID")
    require_text(helper, "candidate_startup_metadata()", "safe candidate startup metadata")
    require_text(
        helper,
        "entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}} user={{json .Config.User}} workdir={{json .Config.WorkingDir}}",
        "bounded startup config inspection",
    )
    for path in (
        "/usr/bin/tini",
        "/usr/local/bin/start-remote-dev-web",
        "/usr/local/lib/remote-dev-runtime.sh",
        "/usr/local/bin/remote-dev-launcher",
        "/usr/bin/env",
        "/bin/bash",
        "/usr/bin/python3",
    ):
        require_text(helper, path, "startup path metadata")

    require_text(helper, "strict_launcher_preflight()", "strict launcher diagnostic preflight")
    for required in (
        "--user 65532:65532",
        "--security-opt no-new-privileges:true",
        "--cap-drop ALL",
        "--read-only",
        "--pids-limit 64",
        "--ipc private",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755",
        "--env REMOTE_DEV_ROLE=launcher",
        "--env REMOTE_DEV_START_MODE=menu",
        "--env WEB_CHECK_ORIGIN=1",
        "--env WEB_PORT=7680",
        "--env ALLOW_INSECURE_WEB=1",
    ):
        require_text(helper, required, "strict launcher hardening fixture")
    require_text(helper, "docker logs --tail 80", "bounded launcher log diagnostics")
    require_text(helper, "docker logs --tail 40", "bounded component log diagnostics")
    require_text(helper, ".State.ExitCode", "launcher exit-code diagnostics")
    require_text(helper, ".State.OOMKilled", "launcher OOM diagnostics")
    require_text(helper, "component_probe start-script /usr/local/bin/start-remote-dev-web", "start-script isolation probe")
    require_text(helper, "component_probe direct /usr/local/bin/remote-dev-launcher", "direct launcher isolation probe")
    require_text(helper, "--entrypoint /usr/bin/tini", "tini execution probe")
    require_text(helper, "timeout --foreground 15s", "bounded tini probe")
    require(".Config.Env" not in helper, "diagnostics must never dump the candidate environment")
    require("{{json .Config}}" not in helper, "diagnostics must never dump arbitrary candidate config")
    require("docker history" not in helper, "diagnostics must not dump build history")

    require_text(helper, "remote-dev-notices", "exact candidate notice checks")
    require_text(helper, "codex-smoke-test", "exact candidate Codex smoke")
    require_text(helper, "runtime-smoke-test.sh", "exact candidate runtime smoke")
    require_text(helper, "test-web-password-runtime.sh", "exact candidate agent auth smoke")
    require_text(helper, "test-cross-service-isolation.sh", "exact candidate isolation smoke")

    print("Controlled edge security rebuild contract: OK")


if __name__ == "__main__":
    main()
