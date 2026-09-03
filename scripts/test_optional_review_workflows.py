#!/usr/bin/env python3
"""Static regression checks for optional-tool review workflow trust boundaries."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".github/workflows/check-upstream.yml"
ANTIGRAVITY = ROOT / ".github/workflows/review-antigravity-candidate.yml"


def require(text: str, fragment: str, label: str) -> None:
    """Require one architecture marker in workflow text."""
    if fragment not in text:
        raise AssertionError(f"missing {label}: {fragment!r}")


def job_block(text: str, job: str, next_job: str | None = None) -> str:
    """Return one top-level job block from workflow YAML text."""
    marker = f"  {job}:\n"
    start = text.find(marker)
    if start < 0:
        raise AssertionError(f"workflow is missing job {job!r}")
    if next_job is None:
        return text[start:]
    end_marker = f"  {next_job}:\n"
    end = text.find(end_marker, start + len(marker))
    if end < 0:
        raise AssertionError(f"workflow is missing following job {next_job!r}")
    return text[start:end]


def assert_scheduler_contract(text: str) -> None:
    """Lock the non-executing scheduled discovery and separate writer boundary."""
    require(text, 'cron: "17 5 * * *"', "daily review cadence")
    require(text, "group: check-upstream", "shared concurrency group")
    detect = job_block(text, "antigravity-detect", "check")
    writer = job_block(text, "check")

    require(detect, "permissions:\n      contents: read", "read-only Antigravity detector")
    require(detect, "persist-credentials: false", "credential-free detector checkout")
    require(detect, "scripts/detect-antigravity-installer.py", "installer detector")
    require(detect, "scripts/discover-antigravity-payload.py", "static payload discovery")
    require(
        detect,
        '--expected-installer-sha256 "$live_installer_sha"',
        "detected installer hash bound into static discovery",
    )
    require(detect, "scripts/validate-antigravity-review-artifact.py", "artifact validation")
    if 'if [[ "$live_installer_sha" == "$reviewed_installer_sha" ]]' in detect:
        raise AssertionError("scheduled static discovery must not require the installer to be previously executed/reviewed")
    if "scripts/run-antigravity-inspection.py" in detect or "scripts/inspect-antigravity-cli.py" in detect:
        raise AssertionError("scheduled Antigravity discovery must never execute installer/payload inspection")
    if "contents: write" in detect or "pull-requests: write" in detect or "actions: write" in detect:
        raise AssertionError("scheduled Antigravity detector unexpectedly gained write permission")

    require(writer, "needs: antigravity-detect", "writer dependency on read-only detector")
    require(writer, "actions: write", "writer action-dispatch permission")
    require(writer, "contents: write", "writer branch-maintenance permission")
    require(writer, "pull-requests: write", "writer PR-maintenance permission")
    require(writer, "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "pinned artifact download action")
    require(writer, "Revalidate Antigravity metadata after crossing into write-capable job", "second trust-boundary validation")
    require(writer, '--live-discovery "$ANTIGRAVITY_DISCOVERY"', "fresh static discovery reconciliation")
    require(writer, 'git diff --cached --quiet', "index-based no-change check")
    require(writer, "https://registry.npmjs.org/ctx7/latest", "fixed Context7 registry endpoint")
    require(writer, "--max-filesize 65536", "bounded Context7 metadata transfer")
    require(writer, "scripts/update-context7-review.py", "Context7 reviewed-pin updater")
    require(writer, "scripts/test-remote-dev-context7-device-login.py", "atomic Context7 reviewed-test maintenance")
    require(
        writer,
        'gh_amd64_sha256="$(release_sha256 "$workdir/gh.json" "gh_${latest_gh}_linux_amd64.tar.gz")"',
        "well-formed GitHub CLI AMD64 digest lookup",
    )
    require(
        writer,
        'gh_arm64_sha256="$(release_sha256 "$workdir/gh.json" "gh_${latest_gh}_linux_arm64.tar.gz")"',
        "well-formed GitHub CLI ARM64 digest lookup",
    )
    require(writer, 'branch="automation/update-upstreams"', "single automation branch")
    if "gh pr merge" in writer or "--auto" in writer:
        raise AssertionError("upstream writer must never merge its own PR")


def assert_antigravity_manual_contract(text: str) -> None:
    """Lock the one human-approved vendor execution stage."""
    require(text, "group: check-upstream", "shared concurrency group")
    require(text, "installer_sha256:", "explicit installer admission input")
    require(text, "payload_sha256:", "explicit payload admission input")
    if "discover-payload" in text or "inspect-payload" in text:
        raise AssertionError("manual workflow must not retain redundant multi-stage review choices")

    candidate = job_block(text, "candidate", "maintain-pr")
    writer = job_block(text, "maintain-pr")
    require(candidate, "permissions:\n      contents: read", "read-only vendor-execution job")
    require(candidate, "persist-credentials: false", "credential-free vendor-execution checkout")
    require(candidate, "scripts/run-antigravity-inspection.py", "strict prefetch/hash inspection gate")
    require(candidate, "scripts/validate-antigravity-review-artifact.py", "pre-upload artifact validation")
    if "scripts/inspect-antigravity-cli.py" in candidate:
        raise AssertionError("workflow must not invoke the legacy live downloader directly")
    if "contents: write" in candidate or "pull-requests: write" in candidate or "actions: write" in candidate:
        raise AssertionError("vendor-execution job unexpectedly gained write permission")

    require(writer, "actions: write", "writer action permission")
    require(writer, "contents: write", "writer content permission")
    require(writer, "pull-requests: write", "writer PR permission")
    require(writer, "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "pinned metadata download")
    require(writer, "Revalidate artifact after crossing into the write-capable job", "post-download artifact validation")
    require(writer, "inspection requires a previously validated static candidate", "mandatory static candidate gate")
    require(writer, "payload approval does not match the pending statically discovered candidate", "exact payload admission gate")
    require(writer, 'branch="automation/update-upstreams"', "single automation branch")
    if "gh pr merge" in writer or "--auto" in writer:
        raise AssertionError("Antigravity review writer must never merge its own PR")


def main() -> None:
    """Run workflow architecture assertions."""
    upstream = UPSTREAM.read_text(encoding="utf-8")
    antigravity = ANTIGRAVITY.read_text(encoding="utf-8")
    assert_scheduler_contract(upstream)
    assert_antigravity_manual_contract(antigravity)
    print("Optional review workflow contracts: OK")


if __name__ == "__main__":
    main()
