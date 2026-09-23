#!/usr/bin/env python3
"""Validate the bounded Remote Dev image release-channel contract."""

from __future__ import annotations

import argparse
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


def validate_candidate(root: Path) -> None:
    gate = read(root, ".github/workflows/publish-pr-candidate-amd64.yml")
    worker = read(root, ".github/workflows/publish-pr-candidate-worker-amd64.yml")

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
            "cache-mode: write-only",
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
            "actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
        ),
        "candidate build",
    )
    reject(build, ("packages: write", "actions/upload-artifact@", "restore-keys:"), "candidate build")

    verify = active(bounded(worker, "  verify:\n", "\n  publish:\n", "candidate verify"))
    require(
        verify,
        (
            "cache-mode: read",
            "actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9",
            "fail-on-cache-miss: true",
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
    reject(verify, ("packages: write", "restore-keys:"), "candidate verify")

    publish = active(
        bounded(worker, "  publish:\n", "\n  cleanup:\n", "candidate publication")
    )
    require(
        publish,
        (
            "cache-mode: read",
            "actions: read",
            "issues: read",
            "packages: write",
            "pull-requests: write",
            "fail-on-cache-miss: true",
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
            '--tag "${image}:edge',
            '--tag "${image}:stable',
            '--tag "${image}:latest"',
        ),
        "candidate publication",
    )

    cleanup = active(bounded(worker, "  cleanup:\n", None, "candidate cleanup"))
    require(
        cleanup,
        (
            "needs: [build, verify, publish]",
            "if: always() && needs.build.result == 'success'",
            "cache-mode: none",
            "actions: write",
            "actions/caches?key=${CACHE_KEY}&ref=refs/heads/main",
            'if [[ "$deleted_count" != "1" ]]',
        ),
        "candidate cleanup",
    )


def validate_other_channels(root: Path) -> None:
    edge = read(root, ".github/workflows/publish-edge-amd64.yml")
    stable = read(root, ".github/workflows/publish-amd64.yml")

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
    edge_publish = active(
        bounded(
            edge,
            "      - name: Promote one scanned and smoke-tested digest to canonical edge tags\n",
            None,
            "edge publication",
        )
    )
    require(
        edge_publish,
        (
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:edge"',
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:edge-amd64"',
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:sha-${GITHUB_SHA}"',
            'for tag in edge edge-amd64 "sha-${GITHUB_SHA}"; do',
        ),
        "edge publication",
    )
    reject(
        edge_publish,
        (':dev"', ':dev-amd64"', ':stable"', ':stable-amd64"', ':latest"'),
        "edge publication",
    )

    stable_trigger = active(bounded(stable, "on:\n", "\npermissions:", "stable trigger"))
    require(stable_trigger, ('tags:\n      - "v*"',), "stable trigger")
    stable_tag_validation = active(
        bounded(
            stable,
            "      - name: Validate stable release tag\n",
            "      - name: Require the tagged commit from main history\n",
            "stable tag validation",
        )
    )
    require(
        stable_tag_validation,
        ('if [[ ! "$GITHUB_REF_NAME" =~ ^v[0-9]+\\.[0-9]+\\.[0-9]+$ ]]',),
        "stable tag validation",
    )
    stable_main_guard = active(
        bounded(
            stable,
            "      - name: Require the tagged commit from main history\n",
            "      - name: Validate repository configuration\n",
            "stable main guard",
        )
    )
    require(
        stable_main_guard,
        ('if ! git merge-base --is-ancestor "$GITHUB_SHA" refs/remotes/origin/main; then',),
        "stable main guard",
    )
    stable_publish = active(
        bounded(
            stable,
            "      - name: Promote one scanned digest to canonical stable tags\n",
            None,
            "stable publication",
        )
    )
    require(
        stable_publish,
        (
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:${GITHUB_REF_NAME}"',
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:stable"',
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:stable-amd64"',
            '--tag "ghcr.io/${NAMESPACE}/remote-dev:latest"',
            'for tag in "$GITHUB_REF_NAME" stable stable-amd64 latest; do',
        ),
        "stable publication",
    )
    reject(
        stable_publish,
        (':dev"', ':dev-amd64"', ':edge"', ':edge-amd64"'),
        "stable publication",
    )


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
    args = parser.parse_args()
    try:
        validate(args.root.resolve())
    except ContractError as exc:
        print(f"ERROR: {exc}")
        return 1
    print("Release channel contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
