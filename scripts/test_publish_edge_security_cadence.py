#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/publish-edge-amd64.yml"
HELPER = ROOT / "scripts/validate-edge-publication-candidate.sh"
RESOLVER = ROOT / "scripts/resolve-oci-platform-manifest.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(text: str, needle: str, label: str) -> None:
    require(needle in text, f"missing {label}: {needle}")


def run_resolver(index: dict[str, object]) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="remote-dev-oci-resolver-") as temp_dir:
        temp = Path(temp_dir)
        index_path = temp / "index.json"
        index_path.write_text(json.dumps(index), encoding="utf-8")
        docker_path = temp / "docker"
        docker_path.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"${1:-}\" == buildx && \"${2:-}\" == imagetools && \"${3:-}\" == inspect && \"${5:-}\" == --raw ]]; then\n"
            "  cat \"$FAKE_OCI_INDEX\"\n"
            "  exit 0\n"
            "fi\n"
            "echo 'unexpected fake docker invocation' >&2\n"
            "exit 64\n",
            encoding="utf-8",
        )
        docker_path.chmod(0o755)
        env = os.environ.copy()
        env["FAKE_OCI_INDEX"] = str(index_path)
        env["PATH"] = f"{temp}:{env['PATH']}"
        return subprocess.run(
            [
                "bash",
                str(RESOLVER),
                "ghcr.io/experience83/remote-dev@sha256:" + "1" * 64,
                "linux",
                "amd64",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )


def test_resolver_contract() -> None:
    runnable_digest = "sha256:" + "a" * 64
    runnable = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": runnable_digest,
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    attestation = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": "sha256:" + "b" * 64,
        "platform": {"os": "unknown", "architecture": "unknown"},
        "annotations": {
            "vnd.docker.reference.type": "attestation-manifest",
            "vnd.docker.reference.digest": runnable_digest,
        },
    }
    index = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.index.v1+json",
        "manifests": [runnable, attestation],
    }
    result = run_resolver(index)
    require(result.returncode == 0, f"resolver rejected valid OCI index: {result.stderr}")
    require(
        result.stdout.strip() == f"ghcr.io/experience83/remote-dev@{runnable_digest}",
        "resolver did not return the unique runnable linux/amd64 child",
    )

    duplicate = dict(index)
    duplicate["manifests"] = [runnable, dict(runnable, digest="sha256:" + "c" * 64), attestation]
    result = run_resolver(duplicate)
    require(result.returncode != 0, "resolver must fail closed on duplicate runnable platform manifests")

    no_runnable = dict(index)
    no_runnable["manifests"] = [attestation]
    result = run_resolver(no_runnable)
    require(result.returncode != 0, "resolver must fail closed when no runnable platform manifest exists")

    wrong_root = dict(index)
    wrong_root["mediaType"] = "application/vnd.oci.image.manifest.v1+json"
    result = run_resolver(wrong_root)
    require(result.returncode != 0, "resolver must reject a root digest that is not an image index")


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    resolver = RESOLVER.read_text(encoding="utf-8")

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

    base_build = workflow.index("Build untagged edge base candidate")
    base_resolve = workflow.index("Resolve exact edge base AMD64 manifest")
    runtime_build = workflow.index("Build untagged edge Remote Dev candidate")
    runtime_resolve = workflow.index("Resolve exact edge Remote Dev AMD64 manifest")
    helper_step = workflow.index("Smoke-test the exact publication candidates")
    base_sbom = workflow.index("Generate exact edge base SPDX SBOM")
    runtime_sbom = workflow.index("Generate exact edge Remote Dev SPDX SBOM")
    base_scan = workflow.index("Scan exact edge base candidate for critical vulnerabilities")
    runtime_scan = workflow.index("Scan exact edge Remote Dev candidate for critical vulnerabilities")
    gate = workflow.index("Enforce no fixable critical vulnerabilities")
    promote = workflow.index("Promote one scanned and smoke-tested digest to canonical edge tags")
    require(
        base_build
        < base_resolve
        < runtime_build
        < runtime_resolve
        < helper_step
        < base_sbom
        < runtime_sbom
        < base_scan
        < runtime_scan
        < gate
        < promote,
        "platform resolution, candidate smoke, SPDX, Trivy and gate must all precede promotion",
    )

    require_text(
        workflow,
        'BASE_IMAGE=${{ steps.base_manifest.outputs.ref }}',
        "runtime build pinned to resolved base AMD64 manifest",
    )
    require_text(
        workflow,
        '"ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}"',
        "base publication index helper reference",
    )
    require_text(workflow, '"$BASE_MANIFEST_REF"', "exact base runnable manifest helper reference")
    require_text(
        workflow,
        '"ghcr.io/${NAMESPACE}/remote-dev@${REMOTE_DEV_DIGEST}"',
        "runtime publication index helper reference",
    )
    require_text(workflow, '"$REMOTE_DEV_MANIFEST_REF"', "exact runtime runnable manifest helper reference")
    require(
        workflow.count("image-ref: ${{ steps.base_manifest.outputs.ref }}") == 2,
        "base SBOM and Trivy scan must both use the runnable AMD64 manifest",
    )
    require(
        workflow.count("image-ref: ${{ steps.runtime_manifest.outputs.ref }}") == 2,
        "runtime SBOM and Trivy scan must both use the runnable AMD64 manifest",
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
    require_text(workflow, 'base_ref="ghcr.io/${NAMESPACE}/remote-dev-base@${BASE_DIGEST}"', "base index promotion")
    require_text(workflow, 'runtime_ref="ghcr.io/${NAMESPACE}/remote-dev@${REMOTE_DEV_DIGEST}"', "runtime index promotion")

    lowered = workflow.lower()
    for forbidden in (
        ":stable",
        ":latest",
        "stable-amd64",
        "latest =",
        "pull_request_target",
    ):
        require(forbidden not in lowered, f"forbidden surface in edge publisher: {forbidden}")

    require_text(resolver, "docker buildx imagetools inspect", "registry-level index inspection")
    require_text(resolver, "--raw", "raw OCI descriptor inspection")
    require_text(resolver, 'platform.os == $os', "operating-system descriptor filter")
    require_text(resolver, 'platform.architecture == $arch', "architecture descriptor filter")
    require_text(resolver, 'vnd.docker.reference.type', "attestation descriptor exclusion")
    require_text(resolver, "expected exactly one runnable", "unique runnable manifest guard")
    require_text(resolver, "application/vnd.oci.image.index.v1+json", "OCI image-index guard")
    require_text(resolver, "application/vnd.oci.image.manifest.v1+json", "OCI runnable-manifest guard")
    test_resolver_contract()

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
    require_text(helper, '"$resolver" "$base_index_ref" linux amd64', "base index-to-manifest binding")
    require_text(helper, '"$resolver" "$runtime_index_ref" linux amd64', "runtime index-to-manifest binding")
    require_text(helper, '"$resolved_base_ref" == "$base_ref"', "exact base child membership assertion")
    require_text(helper, '"$resolved_runtime_ref" == "$runtime_ref"', "exact runtime child membership assertion")
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
        "/usr/local/lib/remote-dev/remote-dev-runtime.sh",
        "/usr/local/bin/remote-dev-launcher",
        "/usr/bin/env",
        "/bin/bash",
        "/etc/mise/config.toml",
        "/etc/mise/config.lock",
        "/opt/remote-dev/mise/shims/python",
        "/opt/remote-dev/mise/installs/python",
    ):
        require_text(helper, path, "startup path metadata")
    require(
        "/usr/local/lib/remote-dev-runtime.sh" not in helper,
        "startup diagnostics must use the installed runtime library path",
    )
    require(
        "/usr/bin/python3" not in helper,
        "startup diagnostics must not assume a distro-owned Python interpreter",
    )

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
    require_text(
        helper,
        'docker logs --tail 80 "$container" 2>&1 | tail -n 80 >&2',
        "bounded merged launcher stdout/stderr diagnostics",
    )
    require_text(
        helper,
        'docker logs --tail 40 "$probe_name" 2>&1 | tail -n 40 >&2',
        "bounded merged component stdout/stderr diagnostics",
    )
    require(
        'docker logs --tail 80 "$container" >&2 2>/dev/null' not in helper,
        "launcher diagnostics must not discard container stderr",
    )
    require(
        'docker logs --tail 40 "$probe_name" >&2 2>/dev/null' not in helper,
        "component diagnostics must not discard container stderr",
    )
    require_text(helper, ".State.ExitCode", "launcher exit-code diagnostics")
    require_text(helper, ".State.OOMKilled", "launcher OOM diagnostics")
    require_text(
        helper,
        "component_probe env-python3 /usr/bin/env python3 --version",
        "launcher shebang Python resolution probe",
    )
    require_text(
        helper,
        "component_probe python-launcher /opt/remote-dev/mise/shims/python /usr/local/bin/remote-dev-launcher",
        "direct fixed Python launcher probe",
    )
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
