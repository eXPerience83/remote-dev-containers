#!/usr/bin/env python3
"""Read-only identity gate for the owner-dispatched Stable publisher (#380)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = "experience83/remote-dev-containers"
OWNER_ID = "16572400"
SHA = r"[0-9a-f]{40}"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"


class ReleasePolicyError(ValueError):
    """The requested release identity is not authorized."""


def validate_dispatch(env, versions, current_main, checkout_sha):
    """Require a fresh owner dispatch of the exact current reviewed main SHA."""
    if env.get("GITHUB_REPOSITORY", "").lower() != REPOSITORY:
        raise ReleasePolicyError("Unexpected repository")
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or env.get("GITHUB_REF") != "refs/heads/main":
        raise ReleasePolicyError("Stable requires a manual dispatch from main")
    if env.get("GITHUB_ACTOR_ID") != OWNER_ID or env.get("GITHUB_RUN_ATTEMPT") != "1":
        raise ReleasePolicyError("Stable requires a fresh owner dispatch; reruns are forbidden")
    if env.get("DRY_RUN") not in {"true", "false"}:
        raise ReleasePolicyError("dry_run must be an explicit boolean")
    selected = env.get("RELEASE_SHA", "")
    if not re.fullmatch(SHA, selected):
        raise ReleasePolicyError("Expected the full lowercase reviewed commit SHA")
    if any(sha != selected for sha in (
        env.get("GITHUB_SHA"), env.get("GITHUB_WORKFLOW_SHA"), current_main, checkout_sha
    )):
        raise ReleasePolicyError("Reviewed SHA, workflow, checkout and current main must agree")
    tag = env.get("RELEASE_TAG", "")
    if not re.fullmatch("v" + VERSION, tag):
        raise ReleasePolicyError("Expected exact vMAJOR.MINOR.PATCH")
    pins = [line for line in versions.splitlines() if re.match(r"^\s*(?:export\s+)?BASE_VERSION\b", line)]
    if pins != ["BASE_VERSION=" + tag[1:]]:
        raise ReleasePolicyError("Tag must match one canonical literal BASE_VERSION pin")
    return tag, selected


def main():
    # No mutation; GH_TOKEN needs read access only. Do not source versions.env.
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=15
    ).strip()
    response = json.loads(subprocess.check_output(
        ["gh", "api", "--method", "GET", f"repos/{REPOSITORY}/git/ref/heads/main"],
        text=True, timeout=30
    ))
    if response["ref"] != "refs/heads/main" or response["object"]["type"] != "commit":
        raise ReleasePolicyError("Unexpected main ref response")
    tag, selected = validate_dispatch(
        os.environ, Path("versions.env").read_text(encoding="utf-8"),
        response["object"]["sha"], checkout_sha
    )
    print(f"Stable dispatch identity verified: {tag} at {selected}")
    # This identity check is necessary but not sufficient to authorize publication.


if __name__ == "__main__":
    main()
