#!/usr/bin/env python3
"""Read-only identity gate for the owner-dispatched Stable publisher (#380)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPOSITORY = "experience83/remote-dev-containers"
OWNER_ID = "16572400"
SHA = r"[0-9a-f]{40}"
DIGEST = r"sha256:[0-9a-f]{64}"
EDGE_WORKFLOW = 318911668
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


def validate_edge_receipt(receipt, selected, edge_run, accepted_digest):
    """Bind the owner's acceptance to the successful exact Edge run attempt."""
    if not re.fullmatch(DIGEST, accepted_digest):
        raise ReleasePolicyError("Expected the owner-accepted immutable Edge runtime index digest")
    expected = {
        "source_sha": selected,
        "run_id": str(edge_run["id"]),
        "run_attempt": str(edge_run["run_attempt"]),
        "runtime_digest": accepted_digest,
    }
    if not isinstance(receipt, dict) or set(receipt) != {*expected, "base_digest"}:
        raise ReleasePolicyError("Malformed Edge promotion receipt")
    if any(receipt[key] != value for key, value in expected.items()):
        raise ReleasePolicyError("Edge promotion receipt differs from accepted source, run or digest")
    if not isinstance(receipt["base_digest"], str) or not re.fullmatch(DIGEST, receipt["base_digest"]):
        raise ReleasePolicyError("Malformed Edge base index digest")
    return receipt["base_digest"], receipt["runtime_digest"]


def read_edge_receipt(edge_run):
    name = f"edge-promotion-receipt-{edge_run['run_attempt']}"
    pages = api(f"actions/runs/{edge_run['id']}/artifacts?per_page=100", paginate=True)
    matches = [artifact for page in pages for artifact in page["artifacts"]
               if artifact["name"] == name]
    if len(matches) != 1 or matches[0].get("expired") is not False:
        raise ReleasePolicyError("Exact Edge promotion receipt missing, ambiguous or expired")
    size = matches[0].get("size_in_bytes")
    if type(size) is not int or not 0 < size <= 16384:
        raise ReleasePolicyError("Unexpected Edge promotion receipt artifact size")
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(
            ["gh", "run", "download", str(edge_run["id"]), "--repo", REPOSITORY,
             "--name", name, "--dir", directory],
            check=True, timeout=60,
        )
        file = Path(directory) / "edge-promotion-receipt.json"
        if list(Path(directory).iterdir()) != [file] or file.is_symlink() or not file.is_file():
            raise ReleasePolicyError("Unexpected Edge promotion receipt files")
        if file.stat().st_size > 4096:
            raise ReleasePolicyError("Edge promotion receipt too large")
        return json.loads(file.read_text(encoding="utf-8"))


def read_registry_digest(image, selected):
    ref = f"ghcr.io/experience83/{image}:sha-{selected}"
    raw = subprocess.check_output(
        ["docker", "buildx", "imagetools", "inspect", ref,
         "--format", "{{json .Manifest.Digest}}"],
        text=True, timeout=90,
    )
    digest = json.loads(raw)
    if not isinstance(digest, str) or not re.fullmatch(DIGEST, digest):
        raise ReleasePolicyError("Malformed source-addressed Edge index digest")
    return digest


def verify_accepted_edge(selected, edge_run, accepted_digest):
    if not re.fullmatch(DIGEST, accepted_digest):
        raise ReleasePolicyError("Expected the owner-accepted immutable Edge runtime index digest")
    base, runtime = validate_edge_receipt(read_edge_receipt(edge_run), selected, edge_run, accepted_digest)
    if (read_registry_digest("remote-dev-base", selected) != base
            or read_registry_digest("remote-dev", selected) != runtime):
        raise ReleasePolicyError("Source-addressed Edge aliases differ from accepted promotion receipt")


def verify_required_workflows(selected, accepted_digest):
    pages = api(f"actions/runs?head_sha={selected}&per_page=100", paginate=True)
    runs = validate_runs(pages, selected)
    for workflow, run in runs.items():
        jobs = api(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100", paginate=True)
        validate_jobs(jobs, workflow)
    verify_accepted_edge(selected, runs[EDGE_WORKFLOW], accepted_digest)
    # Detect a changed latest run or rerun while inspecting jobs and Edge receipt.
    fresh = validate_runs(api(f"actions/runs?head_sha={selected}&per_page=100", paginate=True), selected)
    if any((run["id"], run["run_attempt"]) != (fresh[workflow]["id"], fresh[workflow]["run_attempt"])
           for workflow, run in runs.items()):
        raise ReleasePolicyError("Required workflow evidence changed; dispatch again")


LEGACY_WORKFLOW = 318438492


def require_retired_publisher():
    workflow = api(f"actions/workflows/{LEGACY_WORKFLOW}")
    if (workflow.get("id") != LEGACY_WORKFLOW
            or workflow.get("path") != ".github/workflows/publish-amd64.yml"
            or workflow.get("state") != "disabled_manually"):
        raise ReleasePolicyError("Legacy tag publisher must be explicitly disabled")


def read_tag(tag, selected):
    """An absent tag is distinct from a conflicting tag or failed API read."""
    ref = f"refs/tags/{tag}"
    matches = [item for item in api(f"git/matching-refs/tags/{tag}")
               if item["ref"] == ref]
    if not matches:
        return False
    if (len(matches) != 1 or matches[0]["object"]["type"] != "commit"
            or matches[0]["object"]["sha"] != selected):
        raise ReleasePolicyError("Existing tag does not name the exact reviewed commit")
    return True


def write_api(endpoint, payload):
    return json.loads(subprocess.check_output(
        ["gh", "api", "--method", "POST", f"repos/{REPOSITORY}/{endpoint}", "--input", "-"],
        input=json.dumps(payload), text=True, timeout=60,
    ))


def require_current_main(selected):
    response = api("git/ref/heads/main")
    if (response["ref"] != "refs/heads/main"
            or response["object"]["type"] != "commit"
            or response["object"]["sha"] != selected):
        raise ReleasePolicyError("Reviewed main changed; dispatch again")


def ensure_tag(tag, selected):
    require_retired_publisher()
    require_current_main(selected)
    if not read_tag(tag, selected):
        write_api("git/refs", {"ref": f"refs/tags/{tag}", "sha": selected})
    if not read_tag(tag, selected):
        raise ReleasePolicyError("Release tag readback failed")


def require_tag(tag, selected):
    require_retired_publisher()
    require_current_main(selected)
    if not read_tag(tag, selected):
        raise ReleasePolicyError("Exact release tag must exist before publishing")


def read_image_tag_digest(image, tag):
    raw = subprocess.check_output(
        ["docker", "buildx", "imagetools", "inspect",
         f"ghcr.io/experience83/{image}:{tag}", "--format", "{{json .Manifest.Digest}}"],
        text=True, timeout=90,
    )
    digest = json.loads(raw)
    if not isinstance(digest, str) or not re.fullmatch(DIGEST, digest):
        raise ReleasePolicyError("Malformed Stable index digest")
    return digest


def verify_stable_aliases(tag, base, runtime):
    for digest in (base, runtime):
        if not re.fullmatch(DIGEST, digest):
            raise ReleasePolicyError("Expected exact published Stable index digests")
    for image, aliases, expected in (
        ("remote-dev-base", (tag, "stable-amd64"), base),
        ("remote-dev", (tag, "stable", "stable-amd64", "latest"), runtime),
    ):
        for alias in aliases:
            if read_image_tag_digest(image, alias) != expected:
                raise ReleasePolicyError(f"Stable alias differs from published digest: {image}:{alias}")


def release_fields(tag, selected, base, runtime, accepted_edge):
    body = (
        f"Reviewed source: {selected}\n\n"
        f"[Changelog](https://github.com/{REPOSITORY}/blob/{selected}/CHANGELOG.md)\n\n"
        f"- Accepted Edge runtime: {accepted_edge}\n"
        f"- Stable base: ghcr.io/experience83/remote-dev-base@{base}\n"
        f"- Stable runtime: ghcr.io/experience83/remote-dev@{runtime}\n"
    )
    return {"tag_name": tag, "name": tag, "body": body, "draft": False, "prerelease": False}


def find_release(tag):
    matches = [item for page in api("releases?per_page=100", paginate=True)
               for item in page if item["tag_name"] == tag]
    if len(matches) > 1:
        raise ReleasePolicyError("Multiple GitHub Releases for exact tag")
    return matches[0] if matches else None


def verify_release_record(release, expected):
    if not isinstance(release, dict) or any(
        release.get(key) != value for key, value in expected.items()
    ):
        raise ReleasePolicyError("GitHub Release differs from exact expected publication")
    if type(release.get("id")) is not int:
        raise ReleasePolicyError("Invalid GitHub Release identity")


def finalize_release(tag, selected, base, runtime, accepted_edge):
    require_tag(tag, selected)
    verify_stable_aliases(tag, base, runtime)
    expected = release_fields(tag, selected, base, runtime, accepted_edge)
    existing = find_release(tag)
    if existing is None:
        require_tag(tag, selected)
        verify_stable_aliases(tag, base, runtime)
        created = write_api("releases", {**expected, "target_commitish": selected, "make_latest": "true"})
        verify_release_record(created, expected)
    else:
        verify_release_record(existing, expected)
    actual = find_release(tag)
    verify_release_record(actual, expected)
    if api("releases/latest").get("id") != actual["id"]:
        raise ReleasePolicyError("Exact GitHub Release is not latest; manual reconciliation required")
    require_tag(tag, selected)
    verify_stable_aliases(tag, base, runtime)


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
    verify_required_workflows(selected, os.environ.get("ACCEPTED_EDGE_DIGEST", ""))
    if api("git/ref/heads/main") != response:
        raise ReleasePolicyError("main changed during workflow validation")
    print(f"Stable dispatch identity, required workflows and accepted Edge verified: {tag} at {selected}")
    # This identity check is necessary but not sufficient to authorize publication.


if __name__ == "__main__":
    main()
