#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github/workflows/rescan-published-images.yml"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def require_text(text: str, needle: str, label: str) -> None:
    require(needle in text, f"missing {label}: {needle}")


def main() -> None:
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
