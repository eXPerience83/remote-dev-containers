#!/usr/bin/env python3
"""Validate the bounded Remote Dev image release-channel contract."""

from __future__ import annotations

import argparse
from pathlib import Path


class ContractError(RuntimeError):
    pass


def read(root: Path, relative: str) -> str:
    path = root / relative
    try:
        return path.read_text(encoding="utf-8")
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
    """Return non-comment workflow lines so comments cannot satisfy the contract."""
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
            raise ContractError(f"{label}: forbidden cross-channel token {token!r}")


def validate(root: Path) -> None:
    candidate = read(root, ".github/workflows/publish-pr-candidate-amd64.yml")
    edge = read(root, ".github/workflows/publish-edge-amd64.yml")
    stable = read(root, ".github/workflows/publish-amd64.yml")
    releases = read(root, "docs/releases.md")
    releases_es = read(root, "docs/releases.es.md")
    env_example = read(root, ".env.example")

    candidate_concurrency = active(
        bounded(candidate, "concurrency:\n", "\njobs:\n", "candidate concurrency")
    )
    require(
        candidate_concurrency,
        ("group: publish-pr-candidate-dev-amd64", "cancel-in-progress: false"),
        "candidate concurrency",
    )

    candidate_job_gate = active(
        bounded(candidate, "    if: >-\n", "    runs-on:", "candidate job gate")
    )
    require(
        candidate_job_gate,
        (
            "github.event.issue.pull_request &&",
            "startsWith(github.event.comment.body, '/publish-candidate ') &&",
            "github.event.comment.user.login == github.repository_owner",
        ),
        "candidate job gate",
    )

    candidate_authorization = active(
        bounded(
            candidate,
            "      - name: Resolve and authorize the pull request\n",
            "      - name: Checkout the exact pull-request head\n",
            "candidate authorization",
        )
    )
    require(
        candidate_authorization,
        (
            'if [[ ! "$requested_sha" =~ ^[0-9a-f]{40}$ ]]',
            'if [[ "$head_repo" != "$GITHUB_REPOSITORY" ]]',
            'if [[ "$base_ref" != main ]]',
            'if [[ "$state" != open ]]',
            'if [[ "$requested_sha" != "$head_sha" ]]',
        ),
        "candidate authorization",
    )

    candidate_publish = active(
        bounded(
            candidate,
            "      - name: Publish the candidate and promote the dev channel\n",
            "      - name: Comment the exact candidate on the pull request\n",
            "candidate publication",
        )
    )
    require(
        candidate_publish,
        (
            'tag="candidate-pr-${PR_NUMBER}-${SHORT_SHA}"',
            'docker push "$ref"',
            '--tag "${image}:dev"',
            '--tag "${image}:dev-amd64"',
            'for published_tag in "$tag" dev dev-amd64; do',
            'if [[ "$actual_digest" != "$digest" ]]',
        ),
        "candidate publication",
    )
    reject(
        candidate_publish,
        ('--tag "${image}:edge', '--tag "${image}:stable', '--tag "${image}:latest"'),
        "candidate publication",
    )

    edge_trigger = active(bounded(edge, "on:\n", "\npermissions:", "edge trigger"))
    require(
        edge_trigger,
        ("push:\n    branches:\n      - main",),
        "edge trigger",
    )
    edge_guard = active(
        bounded(
            edge,
            "      - name: Require the main branch\n",
            "      - name: Validate repository configuration\n",
            "edge main guard",
        )
    )
    require(
        edge_guard,
        ('if [[ "$GITHUB_REF" != "refs/heads/main" ]]',),
        "edge main guard",
    )
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

    stable_trigger = active(
        bounded(stable, "on:\n", "\npermissions:", "stable trigger")
    )
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
