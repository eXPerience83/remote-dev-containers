#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/publish-edge-amd64.yml"
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


def named_workflow_step(workflow: str, name: str) -> str:
    """Return only the uniquely named job step, not text from neighboring steps."""
    marker = f"      - name: {name}\n"
    require(workflow.count(marker) == 1, f"expected exactly one workflow step: {name}")
    start = workflow.index(marker)
    end = workflow.find("\n      - ", start + len(marker))
    return workflow[start:] if end == -1 else workflow[start:end]


def validate_python_315_publisher_wiring(workflow: str) -> None:
    """Require the reviewed Python 3.15 pin in the owning metadata and build fields."""
    metadata = named_workflow_step(workflow, "Resolve image metadata")
    require_text(metadata, "id: metadata", "named metadata step id")
    _, separator, metadata_run = metadata.partition("\n        run: |\n")
    require(bool(separator), "image metadata step must have a run block")
    require_text(
        metadata_run,
        'echo "python_315_version=$PYTHON_315_VERSION" >> "$GITHUB_OUTPUT"',
        "Python 3.15 output inside the image metadata run block",
    )

    base = named_workflow_step(workflow, "Build untagged edge base candidate")
    require_text(base, "id: base", "named base candidate step id")
    require_text(base, "file: images/base/Dockerfile", "base candidate Dockerfile")
    _, separator, build_args = base.partition("\n          build-args: |\n")
    require(bool(separator), "base candidate step must declare build arguments")
    build_args = build_args.partition("\n          labels:")[0]
    require_text(
        build_args,
        'PYTHON_315_VERSION=${{ steps.metadata.outputs.python_315_version }}',
        "reviewed Python 3.15 pin inside base candidate build arguments",
    )


def validate_trivy_db_cache_reuse(workflow: str) -> None:
    """Only the first scan restores the Actions cache; later scans reuse the local DB."""
    steps = (
        "Generate exact edge base SPDX SBOM",
        "Generate exact edge Remote Dev SPDX SBOM",
        "Scan exact edge base candidate for critical vulnerabilities",
        "Scan exact edge Remote Dev candidate for critical vulnerabilities",
    )
    pin = "uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"
    for index, name in enumerate(steps):
        step = named_workflow_step(workflow, name)
        require_text(step, pin, f"exact pinned Trivy action in {name}")
        if index == 0:
            require("          cache:" not in step,
                    "first edge scan must restore/update DB using the Actions cache")
            require("skip-setup-trivy:" not in step,
                    "first edge scan must install the Trivy binary")
        else:
            require("          skip-setup-trivy: true" in step,
                    f"edge scan must reuse installed Trivy: {name}")
            require(step.count("          cache: false\n") == 1
                    and "          cache: true\n" not in step,
                    f"edge scan must reuse local DB without remote restore: {name}")


def main() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    require_text(workflow, 'cron: "11 1 * * 0"', "weekly Sunday security rebuild")
    require_text(workflow, "workflow_dispatch:", "manual rebuild dispatch")
    require("pull_request:" not in workflow, "publisher must never run from pull_request")
    require_text(workflow, "permissions:\n  contents: read", "read-only workflow default")
    require(workflow.count("packages: write") == 1, "write permission belongs to the publication job")
    require_text(workflow, "persist-credentials: false", "credential-free checkout")
    validate_python_315_publisher_wiring(workflow)
    validate_trivy_db_cache_reuse(workflow)
    test_resolver_contract()
    print("Controlled Edge rebuild and OCI resolver: OK")


if __name__ == "__main__":
    main()
