#!/usr/bin/env python3
"""Validate the bounded Remote Dev image release-channel contract."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


class ContractError(RuntimeError):
    pass


def read(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"unable to read {relative}: {exc}") from exc


def bounded(text: str, start: str, end: str | None, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise ContractError(f"{label}: missing start marker {start!r}")
    if text.find(start, start_index + len(start)) >= 0:
        raise ContractError(f"{label}: duplicate start marker {start!r}")
    if end is None:
        return text[start_index:]
    end_index = text.find(end, start_index + len(start))
    if end_index < 0:
        raise ContractError(f"{label}: missing end marker {end!r}")
    return text[start_index:end_index]


def active(block: str) -> str:
    return "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )


def require(block: str, expected: tuple[str, ...], label: str) -> None:
    for token in expected:
        if token not in block:
            raise ContractError(f"{label}: missing required token {token!r}")


def reject(block: str, forbidden: tuple[str, ...], label: str) -> None:
    for token in forbidden:
        if token in block:
            raise ContractError(f"{label}: forbidden token {token!r}")


def require_transfer_order(block: str, load_step: str, label: str) -> None:
    markers = (
        "      - name: Validate exact same-attempt transfer artifact\n",
        "      - name: Download exact candidate transfer artifact by ID\n",
        "      - name: " + load_step + "\n",
    )
    for marker in markers:
        if block.count(marker) != 1:
            raise ContractError(f"{label}: expected exactly one step {marker.strip()!r}")
    positions = [block.index(marker) for marker in markers]
    if positions != sorted(positions):
        raise ContractError(f"{label}: expected metadata guard, download, then hash/load")
    download = block[positions[1]:positions[2]]
    action = "uses: actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333"
    if download.count(action) != 1 or block.count("uses: actions/download-artifact@") != 1:
        raise ContractError(f"{label}: expected the pinned download action after the guard")


def _candidate_step_scripts(worker: str, name: str) -> list[str]:
    scripts = []
    for step in worker.split(f"      - name: {name}\n")[1:]:
        _, separator, body = step.partition("        run: |\n")
        if not separator:
            raise ContractError(f"candidate fixture: missing run body for {name!r}")
        lines = []
        for line in body.splitlines():
            if line and not line.startswith("          "):
                break
            lines.append(line[10:])
        scripts.append("\n".join(lines) + "\n")
    return scripts


def _exercise_candidate_artifact_guards(worker: str, prefix: str) -> None:
    guards = _candidate_step_scripts(worker, "Validate exact same-attempt transfer artifact")
    cleanup = _candidate_step_scripts(
        worker, "Delete exact same-attempt transfer artifact after build handoff"
    )
    hash_steps = []
    for name in (
        "Verify transfer artifact hash and load image",
        "Hash and load the candidate images",
        "Match the verified archive and load the images",
    ):
        hash_steps.extend(_candidate_step_scripts(worker, name))
    expected_consumers = 2 if prefix == "candidate-images" else 1
    if len(guards) != expected_consumers or len(hash_steps) != expected_consumers:
        raise ContractError("candidate fixture: unexpected guard/hash step count")
    if len(cleanup) != 1:
        raise ContractError("candidate fixture: expected one cleanup step")

    # Exercise the actual shell and jq, but never contact GitHub or Docker.
    stub = """
gh() {
    if [[ "$#" == 2 && "$1" == api ]]; then
        [[ "$2" == "repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID" ]] || return 91
        [[ ! -e "$DELETED" ]] || return 44
        printf '%s\\n' "$METADATA"
    elif [[ "$#" == 4 && "$1 $2 $3" == "api --method DELETE" ]]; then
        [[ "$4" == "repos/$GITHUB_REPOSITORY/actions/artifacts/$ARTIFACT_ID" ]] || return 92
        touch "$DELETED"
        printf 'delete\\n' >> "$TRACE"
    else
        return 93
    fi
}
docker() {
    [[ "$#" == 1 && "$1" == load ]] || return 94
    cat >/dev/null
    printf 'load\\n' >> "$TRACE"
}
"""
    name = f"{prefix}-run-101-attempt-2.tar.gz"
    metadata = {
        "id": 17,
        "name": name,
        "workflow_run": {"id": 101},
        "expired": False,
    }
    head = "a" * 40
    cases = (
        ("valid", {}, {}),
        ("invalid-id", {}, {"ARTIFACT_ID": "17,18"}),
        ("empty-id", {}, {"ARTIFACT_ID": ""}),
        ("different-id", {"id": 18}, {}),
        ("other-run", {"workflow_run": {"id": 102}}, {}),
        ("previous-attempt", {"name": f"{prefix}-run-101-attempt-1.tar.gz"}, {}),
        ("expired", {"expired": True}, {}),
        ("missing-run", {"workflow_run": None}, {}),
        ("wrong-head", {}, {"BUILD_HEAD": "b" * 40}),
        ("wrong-pr", {}, {"BUILD_PR": "9"}),
        ("wrong-comment", {}, {"BUILD_COMMENT": "9"}),
        ("wrong-short", {}, {"BUILD_SHORT": "b" * 12}),
    )

    def run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", stub + script],
            env=env,
            cwd=env["RUNNER_TEMP"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def expect(
        label: str,
        result: subprocess.CompletedProcess[str],
        condition: bool,
        message: str,
    ) -> None:
        if not condition:
            raise ContractError(
                f"candidate fixture {label}: {message}; exit={result.returncode}; "
                f"stdout={result.stdout!r}; stderr={result.stderr!r}"
            )

    for label, metadata_override, env_override in cases:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trace = root / "trace"
            deleted = root / "deleted"
            env = {
                "PATH": os.environ["PATH"],
                "GITHUB_REPOSITORY": "fixture/repository",
                "GITHUB_RUN_ID": "101",
                "GITHUB_RUN_ATTEMPT": "2",
                "RUNNER_TEMP": temporary,
                "ARTIFACT_ID": "17",
                "AUTHORIZED_PR": "3",
                "AUTHORIZED_HEAD": head,
                "AUTHORIZED_COMMENT": "5",
                "BUILD_PR": "3",
                "BUILD_HEAD": head,
                "BUILD_COMMENT": "5",
                "BUILD_SHORT": head[:12],
                "METADATA": json.dumps({**metadata, **metadata_override}),
                "TRACE": str(trace),
                "DELETED": str(deleted),
                **env_override,
            }
            for guard in guards:
                trace.unlink(missing_ok=True)
                transfer = root / "candidate-transfer"
                if transfer.exists():
                    transfer.rmdir()
                result = run(guard + 'printf "download\\n" >> "$TRACE"\n', env)
                expect(
                    label, result, (result.returncode == 0) == (label == "valid"),
                    "unexpected metadata guard exit",
                )
                expect(
                    label, result, trace.exists() == (label == "valid"),
                    "unexpected download side effect",
                )

            # Cleanup intentionally authenticates the artifact, not build outputs.
            # It must never delete another run's or attempt's artifact.
            trace.unlink(missing_ok=True)
            result = run(cleanup[0], env)
            cleanup_allowed = label == "valid" or label.startswith("wrong-")
            expect(
                label, result, (result.returncode == 0) == cleanup_allowed,
                "unexpected cleanup exit",
            )
            expect(label, result, deleted.exists() == cleanup_allowed, "unexpected deletion")
            expect(
                label, result,
                trace.read_text() == "delete\n" if cleanup_allowed and trace.exists()
                else not cleanup_allowed and not trace.exists(),
                "unexpected cleanup trace",
            )
            if cleanup_allowed:
                repeated = run(cleanup[0], env)
                expect(label, repeated, repeated.returncode != 0, "repeat cleanup succeeded")
                expect(
                    label, repeated, trace.exists() and trace.read_text() == "delete\n",
                    "repeat cleanup changed the trace",
                )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        transfer = root / "candidate-transfer"
        transfer.mkdir()
        archive = transfer / name
        payload = gzip.compress(b"synthetic candidate fixture")
        archive.write_bytes(payload)
        trace = root / "trace"
        env = {
            "PATH": os.environ["PATH"],
            "RUNNER_TEMP": temporary,
            "GITHUB_RUN_ID": "101",
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_OUTPUT": str(root / "outputs"),
            "TRACE": str(trace),
            "EXPECTED_SHA256": hashlib.sha256(payload).hexdigest(),
        }
        for script in hash_steps:
            trace.unlink(missing_ok=True)
            valid = run(script, env)
            expect("valid archive", valid, valid.returncode == 0, "load failed")
            expect(
                "valid archive", valid, trace.exists() and trace.read_text() == "load\n",
                "expected one load",
            )
            trace.unlink()
            wrong_hash = run(script, {**env, "EXPECTED_SHA256": "0" * 64})
            expect("wrong hash", wrong_hash, wrong_hash.returncode != 0, "load succeeded")
            expect("wrong hash", wrong_hash, not trace.exists(), "unexpected load")
            archive.unlink()
            missing = run(script, env)
            expect("missing archive", missing, missing.returncode != 0, "load succeeded")
            expect("missing archive", missing, not trace.exists(), "unexpected load")
            archive.write_bytes(payload)


def validate_candidate(root: Path) -> None:
    gate = read(root, ".github/workflows/publish-pr-candidate-amd64.yml")
    worker = read(root, ".github/workflows/publish-pr-candidate-worker-amd64.yml")

    gate_trigger = active(bounded(gate, "on:\n", "\npermissions:", "candidate request trigger"))
    require(gate_trigger, ("issue_comment:\n    types: [created]",), "candidate request trigger")
    reject(
        gate_trigger,
        ("pull_request_target:", "workflow_run:", "push:", "workflow_dispatch:"),
        "candidate request trigger",
    )

    gate_job = active(bounded(gate, "  dispatch:\n", None, "candidate request job"))
    require(
        gate_job,
        (
            "github.event.issue.pull_request &&",
            "startsWith(github.event.comment.body, '/publish-candidate ') &&",
            "github.event.comment.user.login == github.repository_owner",
            "cache-mode: none",
            "actions: write",
            "pull-requests: read",
            "- name: Resolve and authorize the pull request",
            'if [[ ! "$requested_sha" =~ ^[0-9a-f]{40}$ ]]',
            'if [[ "$head_repo" != "$GITHUB_REPOSITORY" ]]',
            'if [[ "$base_ref" != main ]]',
            'if [[ "$state" != open ]]',
            'if [[ "$requested_sha" != "$head_sha" ]]',
            "- name: Dispatch trusted candidate worker",
            "--arg ref main",
            "publish-pr-candidate-worker-amd64.yml/dispatches",
        ),
        "candidate request job",
    )
    reject(
        gate_job,
        ("actions/checkout@", "packages: write", "actions/cache/", "actions/upload-artifact@"),
        "candidate request job",
    )

    trigger = active(bounded(worker, "on:\n", "\npermissions:", "candidate worker trigger"))
    require(
        trigger,
        ("workflow_dispatch:", "pr_number:", "head_sha:", "authorization_comment_id:"),
        "candidate worker trigger",
    )
    reject(
        trigger,
        (
            "push:",
            "pull_request:",
            "pull_request_target:",
            "issue_comment:",
            "workflow_run:",
            "workflow_call:",
            "schedule:",
        ),
        "candidate worker trigger",
    )

    concurrency = active(
        bounded(worker, "concurrency:\n", "\njobs:\n", "candidate worker concurrency")
    )
    require(
        concurrency,
        ("group: publish-pr-candidate-dev-amd64", "cancel-in-progress: false"),
        "candidate worker concurrency",
    )

    build = active(bounded(worker, "  build:\n", "\n  verify:\n", "candidate build"))
    require(
        build,
        (
            "cache-mode: none",
            "contents: read",
            "issues: read",
            "pull-requests: read",
            "- name: Revalidate owner authorization and pull-request head",
            'if [[ "$GITHUB_REF" != "refs/heads/main" ]]',
            "comment_user=\"$(jq -r '.user.login' <<<\"$comment_json\")\"",
            'expected_body="/publish-candidate ${INPUT_HEAD_SHA}"',
            'if [[ "$head_repo" != "$GITHUB_REPOSITORY" ]]',
            'if [[ "$base_ref" != main ]]',
            'if [[ "$state" != open ]]',
            'if [[ "$head_sha" != "$INPUT_HEAD_SHA" ]]',
            "candidate-images-run-${GITHUB_RUN_ID}-attempt-${GITHUB_RUN_ATTEMPT}",
            "- name: Checkout the exact pull-request head",
            "persist-credentials: false",
            'archive_dir="${RUNNER_TEMP}/candidate-transfer"',
            'test ! -L "$archive"',
            "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
            "archive: false",
            "if-no-files-found: error",
            "overwrite: false",
            "retention-days: 1",
            "artifact_id: ${{ steps.transfer.outputs.artifact-id }}",
        ),
        "candidate build",
    )
    reject(build, ("packages: write", "actions/cache/", "actions: write", "restore-keys:"), "candidate build")

    verify = active(bounded(worker, "  verify:\n", "\n  publish:\n", "candidate verify"))
    require(
        verify,
        (
            "cache-mode: none",
            "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333",
            "artifact-ids: ${{ needs.build.outputs.artifact_id }}",
            "skip-decompress: true",
            "digest-mismatch: error",
            "Validate exact same-attempt transfer artifact",
            '[[ "$ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]',
            '(.workflow_run.id | tostring) == $run',
            '.name == $name',
            '.expired == false',
            '$BUILD_HEAD" == "$AUTHORIZED_HEAD"',
            "EXPECTED_SHA256: ${{ needs.build.outputs.archive_sha256 }}",
            'if [[ "$sha256" != "$EXPECTED_SHA256" ]]',
            "- name: Verify embedded candidate identity",
            "- name: Scan base image for critical vulnerabilities",
            "- name: Scan final image for critical vulnerabilities",
            "- name: Enforce no fixable critical vulnerabilities",
            "- name: Upload candidate vulnerability reports on failure",
            "if: failure()",
            "retention-days: 3",
        ),
        "candidate verify",
    )
    reject(verify, ("packages: write", "actions/cache/", "restore-keys:"), "candidate verify")
    require(verify, ("ref: ${{ github.sha }}", "cache: false"), "trusted verifier")
    if verify.count("cache: false") != 2:
        raise ContractError("both candidate Trivy scans must disable shared cache")
    require_transfer_order(verify, "Hash and load the candidate images", "candidate verify")

    publish = active(
        bounded(worker, "  publish:\n", "\n  cleanup:\n", "candidate publication")
    )
    require(
        publish,
        (
            "cache-mode: none",
            "actions: read",
            "issues: read",
            "packages: write",
            "pull-requests: write",
            "artifact-ids: ${{ needs.build.outputs.artifact_id }}",
            "skip-decompress: true",
            "digest-mismatch: error",
            "Validate exact same-attempt transfer artifact",
            '[[ "$ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]',
            '(.workflow_run.id | tostring) == $run',
            '.name == $name',
            '.expired == false',
            '$BUILD_HEAD" == "$AUTHORIZED_HEAD"',
            "- name: Revalidate authorization before registry publication",
            'if [[ "$current_state" != open || "$current_base" != main || "$current_head_repo" != "$GITHUB_REPOSITORY" || "$current_head_sha" != "$AUTHORIZED_SHA" ]]',
            "- name: Publish or reuse immutable candidate tag",
            'tag="candidate-pr-${PR_NUMBER}-${SHORT_SHA}"',
            'expected_version="candidate-pr-${PR_NUMBER}"',
            "existing=false",
            'docker push "$ref"',
            'resolved_revision="$(docker image inspect "$resolved_ref" --format \'{{ index .Config.Labels "org.opencontainers.image.revision" }}\')"',
            'resolved_version="$(docker image inspect "$resolved_ref" --format \'{{ index .Config.Labels "org.opencontainers.image.version" }}\')"',
            'if [[ "$resolved_revision" != "$HEAD_SHA" || "$resolved_version" != "$expected_version" ]]',
            'if [[ "$existing" == false ]]',
            "- name: Revalidate authorization immediately before dev promotion",
            "- name: Promote exact candidate digest to dev aliases",
            '--tag "${image}:dev"',
            '--tag "${image}:dev-amd64"',
            'for published_tag in "$tag" dev dev-amd64; do',
            'if [[ "$actual_digest" != "$IMAGE_DIGEST" ]]',
            'candidate_digest="$(docker buildx imagetools inspect "$IMAGE_REF" --format \'{{json .Manifest.Digest}}\' | tr -d \'"\')"',
            'if [[ "$candidate_digest" != "$IMAGE_DIGEST" ]]',
        ),
        "candidate publication",
    )
    reject(
        publish,
        (
            "actions/checkout@",
            "restore-keys:",
            "actions/cache/",
            '--tag "${image}:edge',
            '--tag "${image}:stable',
            '--tag "${image}:latest"',
        ),
        "candidate publication",
    )

    require_transfer_order(
        publish, "Match the verified archive and load the images", "candidate publication"
    )

    cleanup = active(bounded(worker, "  cleanup:\n", None, "candidate cleanup"))
    require(
        cleanup,
        (
            "needs: [build, verify, publish]",
            "if: always() && needs.build.result == 'success'",
            "cache-mode: none",
            "actions: write",
            "actions/artifacts/${ARTIFACT_ID}",
            '(.workflow_run.id | tostring) == $run',
            '.name == $name',
            'gh api --method DELETE "repos/${GITHUB_REPOSITORY}/actions/artifacts/${ARTIFACT_ID}"',
        ),
        "candidate cleanup",
    )



def validate_other_channels(root: Path) -> None:
    edge = read(root, ".github/workflows/publish-edge-amd64.yml")
    stable = read(root, ".github/workflows/release-stable-amd64.yml")
    if (root / ".github/workflows/publish-amd64.yml").exists():
        raise ContractError("legacy stable publisher must not remain in current source")

    edge_trigger = active(bounded(edge, "on:\n", "\npermissions:", "edge trigger"))
    require(edge_trigger, ("push:\n    branches:\n      - main",), "edge trigger")
    edge_guard = active(
        bounded(
            edge,
            "      - name: Require the main branch\n",
            "      - name: Validate repository configuration\n",
            "edge main guard",
        )
    )
    require(edge_guard, ('if [[ "$GITHUB_REF" != "refs/heads/main" ]]',), "edge main guard")
    stable_trigger = active(bounded(stable, "on:\n", "\npermissions:", "stable trigger"))
    require(stable_trigger, ("workflow_dispatch:", "release_tag:", "release_sha:",
                             "accepted_edge_digest:", "dry_run:", "default: true"), "stable trigger")
    reject(stable_trigger, ("push:", "release:", "pull_request:", "schedule:"), "stable trigger")
    preflight = active(bounded(stable, "  validate:\n", "  publish:\n", "stable preflight"))
    require(preflight, ('contents: read', 'actions: read', 'python3 scripts/stable-release-policy.py',
                        'bash scripts/validate-publication-source.sh stable',
                        '[[ "$DRY_RUN" == true ]]', 'echo "authorized=false" >> "$GITHUB_OUTPUT"',
                        'publication_authorized: ${{ steps.publication_boundary.outputs.authorized }}'), "stable preflight")
    reject(preflight, ("packages: write", "contents: write", "actions: write", "authorized=true"), "stable preflight")
    publisher = active(bounded(stable, "  publish:\n", None, "stable publisher"))
    require(publisher, ("needs: validate", "if: inputs.dry_run == false && needs.validate.outputs.publication_authorized == 'true'",
                        "python3 scripts/stable-release-policy.py",
                        'packages: write', '--tag "$RELEASE_TAG"',
                        'scripts/promote-publication-indexes.sh stable'), "stable publisher")
    reject(publisher, ("github.ref_name", "GITHUB_REF_NAME"), "stable publisher")


def validate_docs(root: Path) -> None:
    releases = read(root, "docs/releases.md")
    releases_es = read(root, "docs/releases.es.md")
    env_example = read(root, ".env.example")

    require(
        releases,
        (
            "`dev` / `dev-amd64`",
            "`edge` / `edge-amd64`",
            "`stable` / `stable-amd64`",
            "`latest`",
            "`latest` is always an alias of `stable`",
            "ghcr.io/experience83/remote-dev:dev-amd64",
            "ghcr.io/experience83/remote-dev:edge-amd64",
            "ghcr.io/experience83/remote-dev:stable-amd64",
            "Spanish version: [`releases.es.md`](releases.es.md)",
        ),
        "English release documentation",
    )
    require(
        releases_es,
        (
            "`dev` / `dev-amd64`",
            "`edge` / `edge-amd64`",
            "`stable` / `stable-amd64`",
            "`latest`",
            "`latest` es siempre un alias de `stable`",
            "ghcr.io/experience83/remote-dev:dev-amd64",
            "ghcr.io/experience83/remote-dev:edge-amd64",
            "ghcr.io/experience83/remote-dev:stable-amd64",
            "Versión inglesa: [`releases.md`](releases.md)",
        ),
        "Spanish release documentation",
    )
    require(
        env_example,
        ("REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:edge-amd64",),
        "Compose environment default",
    )
    reject(
        env_example,
        ("REMOTE_DEV_IMAGE=ghcr.io/experience83/remote-dev:dev",),
        "Compose environment default",
    )


def validate(root: Path) -> None:
    validate_candidate(root)
    validate_other_channels(root)
    validate_docs(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--exercise-candidate-guards",
        action="store_true",
        help="Execute Bash fixtures from this trusted checkout only (not a sandbox).",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.exercise_candidate_guards and root != Path(__file__).resolve().parents[1]:
            raise ContractError("Bash fixtures require the validator's own trusted checkout")
        validate(root)
        if args.exercise_candidate_guards:
            worker = read(root, ".github/workflows/publish-pr-candidate-worker-amd64.yml")
            _exercise_candidate_artifact_guards(worker, "candidate-images")
    except ContractError as exc:
        print(f"ERROR: {exc}")
        return 1
    print("Release channel contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
