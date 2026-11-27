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


# Use the exact repository workflow identities, not human-editable check names.
# Gitleaks is a required PR check; on main the post-merge gates are these three.
REQUIRED_WORKFLOWS = {
    318438490: (".github/workflows/build-amd64.yml", {"push", "workflow_dispatch"}, {"build"}),
    318911668: (".github/workflows/publish-edge-amd64.yml", {"push", "workflow_dispatch", "schedule"}, {"publish-edge"}),
    431908137: ("dynamic/github-code-scanning/codeql", {"dynamic"}, {
        "Analyze (actions)", "Analyze (python)", "Analyze (javascript-typescript)"
    }),
}


def validate_runs(pages, selected):
    """Return latest exact-main run per required workflow; never fall back to old success."""
    latest = {}
    for page in pages:
        for run in page["workflow_runs"]:
            workflow = run["workflow_id"]
            if workflow not in REQUIRED_WORKFLOWS:
                continue
            if run["head_sha"] != selected or run["head_branch"] != "main":
                continue
            path, events, _ = REQUIRED_WORKFLOWS[workflow]
            if run["path"] != path or run["event"] not in events:
                continue
            if workflow not in latest or run["id"] > latest[workflow]["id"]:
                latest[workflow] = run
    for workflow, (path, _, _) in REQUIRED_WORKFLOWS.items():
        run = latest.get(workflow, {})
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            raise ReleasePolicyError(f"Required exact-main workflow missing or not successful: {path}")
    return latest


def validate_jobs(pages, workflow):
    """A successful aggregate cannot substitute for a required successful job."""
    expected = REQUIRED_WORKFLOWS[workflow][2]
    jobs = [job for page in pages for job in page["jobs"]]
    for name in expected:
        matches = [job for job in jobs if job["name"] == name]
        if len(matches) != 1 or matches[0]["status"] != "completed" or matches[0]["conclusion"] != "success":
            raise ReleasePolicyError(f"Required job missing, ambiguous or unsuccessful: {name}")


def api(endpoint, *, paginate=False):
    command = ["gh", "api", "--method", "GET"]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    command.append(f"repos/{REPOSITORY}/{endpoint}")
    return json.loads(subprocess.check_output(command, text=True, timeout=60))


def verify_required_workflows(selected):
    pages = api(f"actions/runs?head_sha={selected}&per_page=100", paginate=True)
    runs = validate_runs(pages, selected)
    for workflow, run in runs.items():
        jobs = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100", paginate=True)
        validate_jobs(jobs, workflow)
    # Detect a changed latest run or rerun while inspecting jobs.
    fresh = validate_runs(api(f"actions/runs?head_sha={selected}&per_page=100", paginate=True), selected)
    if any((run["id"], run["run_attempt"]) != (fresh[workflow]["id"], fresh[workflow]["run_attempt"])
           for workflow, run in runs.items()):
        raise ReleasePolicyError("Required workflow evidence changed; dispatch again")


def main():
    # No mutation; GH_TOKEN needs read access only. Do not source versions.env.
    checkout_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True, timeout=15
    ).strip()
    response = api("git/ref/heads/main")
    if response["ref"] != "refs/heads/main" or response["object"]["type"] != "commit":
        raise ReleasePolicyError("Unexpected main ref response")
    tag, selected = validate_dispatch(
        os.environ, Path("versions.env").read_text(encoding="utf-8"),
        response["object"]["sha"], checkout_sha
    )
    verify_required_workflows(selected)
    if api("git/ref/heads/main") != response:
        raise ReleasePolicyError("main changed during workflow validation")
    print(f"Stable dispatch identity and required workflows verified: {tag} at {selected}")
    # This identity check is necessary but not sufficient to authorize publication.


if __name__ == "__main__":
    main()
