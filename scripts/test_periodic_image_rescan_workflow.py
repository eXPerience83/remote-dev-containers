#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/rescan-published-images.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(text: str, needle: str, label: str) -> None:
    require(needle in text, f"missing {label}: {needle}")


def pinned_login_action_sha(workflow: str, label: str) -> str:
    """Require exactly one immutable docker/login-action v4 reference."""
    lines = [line for line in workflow.splitlines() if "docker/login-action" in line]
    require(len(lines) == 1, f"{label}: expected exactly one GHCR login action")
    match = re.fullmatch(
        r"[ \t]+(?:- )?uses: docker/login-action@([0-9a-f]{40}) # v4[ \t]*",
        lines[0],
    )
    require(match is not None, f"{label}: docker/login-action must use a full v4 commit SHA")
    return match.group(1)


def test_login_action_pin_parser() -> None:
    """Guard against future weak pins without locking tests to a specific digest."""
    sha = "a" * 40
    valid = f"      - uses: docker/login-action@{sha} # v4"
    require(pinned_login_action_sha(valid, "positive fixture") == sha, "valid SHA pin rejected")
    invalid = (
        "      - uses: docker/login-action@v4",
        "      - uses: docker/login-action@" + "a" * 39 + " # v4",
        "      - uses: docker/login-action@" + "g" * 40 + " # v4",
        f"      - uses: docker/login-action@{sha} # v5",
        valid + "\n" + valid,
        f"      # uses: docker/login-action@{sha} # v4",
    )
    for case in invalid:
        try:
            pinned_login_action_sha(case, "negative fixture")
        except AssertionError:
            continue
        raise AssertionError(f"unsafe docker/login-action pin accepted: {case!r}")


def main() -> None:
    test_login_action_pin_parser()
    text = WORKFLOW.read_text(encoding="utf-8")

    require_text(text, 'cron: "23 4 * * 1"', "weekly schedule")
    require_text(text, "workflow_dispatch:", "manual dispatch")
    require("pull_request:" not in text, "rescan workflow must not run from pull_request")
    require("push:" not in text, "rescan workflow must not run from push")
    require_text(text, "permissions: {}", "deny-by-default workflow permissions")
    require(text.count("if: github.ref == 'refs/heads/main'") == 1, "scan main-branch guard")
    require_text(
        text,
        "always() && github.ref == 'refs/heads/main' && needs.scan.outputs.rendered == 'true'",
        "writer main-branch/output guard",
    )

    require_text(text, "contents: read\n      packages: read", "scan read permissions")
    require_text(text, "contents: read\n      issues: write", "writer issue permissions")
    require("packages: write" not in text, "periodic rescan must never write packages")
    require("pull-requests: write" not in text, "periodic rescan must never write PRs")
    require("actions: write" not in text, "periodic rescan must never write Actions")

    # Published GHCR packages may require authentication even for read-only pulls.
    # Keep that auth confined to the main-only scan job, before digest resolution.
    scan_job = text.split("\n  reconcile-alert:", 1)[0]
    login_name = "      - name: Authenticate GHCR for read-only image rescans"
    resolve_name = "      - name: Resolve mutable edge tags to exact digests"
    require(scan_job.count(login_name) == 1, "exactly one read-only GHCR login")
    require(scan_job.count(resolve_name) == 1, "exactly one digest resolve step")
    require(scan_job.index(login_name) < scan_job.index(resolve_name), "login must precede digest resolution")
    login_sha = pinned_login_action_sha(scan_job, "read-only GHCR rescan")
    # Renovate updates these references together. A full SHA is mandatory, but
    # testing one literal SHA would break every legitimate digest update.
    for relative in (
        ".github/workflows/publish-amd64.yml",
        ".github/workflows/publish-edge-amd64.yml",
        ".github/workflows/publish-pr-candidate-worker-amd64.yml",
    ):
        workflow = (ROOT / relative).read_text(encoding="utf-8")
        require(
            pinned_login_action_sha(workflow, relative) == login_sha,
            f"{relative}: docker/login-action SHA differs from periodic rescan",
        )
    require_text(scan_job, "registry: ghcr.io", "fixed GHCR registry")
    require_text(scan_job, "username: ${{ github.actor }}", "GitHub actor identity")
    require_text(scan_job, "password: ${{ github.token }}", "scoped automatic token")
    require("docker/login-action@" not in text.split("\n  reconcile-alert:", 1)[1], "alert writer must not receive registry auth")

    require_text(
        text,
        "ghcr.io/experience83/remote-dev-base edge-amd64",
        "base edge digest resolution",
    )
    require_text(
        text,
        "ghcr.io/experience83/remote-dev edge-amd64",
        "runtime edge digest resolution",
    )
    require_text(
        text,
        "image-ref: ${{ steps.resolve.outputs.base_ref }}",
        "exact base scan reference",
    )
    require_text(
        text,
        "image-ref: ${{ steps.resolve.outputs.runtime_ref }}",
        "exact runtime scan reference",
    )
    require(text.count("cache: false") == 2, "both Trivy scans must disable restored DB cache")
    require_text(text, "trivy --version > trivy-version.txt", "scanner/DB metadata capture")
    require_text(text, "retention-days: 30", "evidence retention")
    require_text(text, "scripts/enforce-trivy-gate.sh", "existing project vulnerability gate")

    require_text(
        text,
        "Revalidate evidence after crossing into write-capable job",
        "write-boundary revalidation",
    )
    require_text(text, "cmp \"$evidence/periodic-rescan-alert.md\"", "alert byte comparison")
    require_text(text, "cmp \"$evidence/periodic-rescan-state.json\"", "state byte comparison")
    require_text(
        text,
        "[security] published image vulnerability alert",
        "stable deduplicated issue title",
    )
    require_text(
        text,
        "<!-- remote-dev-periodic-rescan-alert -->",
        "managed issue marker",
    )
    require_text(text, "gh api --paginate", "pagination-safe issue enumeration")
    require_text(
        text,
        '"repos/${GITHUB_REPOSITORY}/issues?state=all&per_page=100"',
        "direct all-issue API enumeration",
    )
    require_text(text, "select(.pull_request == null)", "exclude pull requests from issue ownership")
    require("gh issue list" not in text, "managed issue lookup must not depend on search/index ranking")
    require_text(text, "gh issue create", "alert creation")
    require_text(text, "gh issue edit", "alert update")
    require_text(text, "gh issue reopen", "alert reopen")
    require_text(text, "gh issue close", "clean alert closure")

    lowered = text.lower()
    for forbidden in (
        "docker push",
        "buildx build --push",
        ":stable",
        ":latest",
        "stable-amd64",
    ):
        require(forbidden not in lowered, f"forbidden publication surface in rescan workflow: {forbidden}")

    print("Periodic image rescan workflow contract: OK")


if __name__ == "__main__":
    main()
