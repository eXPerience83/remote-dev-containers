#!/usr/bin/env python3
"""Static regression checks for optional-tool review workflow trust boundaries."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".github/workflows/check-upstream.yml"
ANTIGRAVITY = ROOT / ".github/workflows/review-antigravity-candidate.yml"


def require(text: str, fragment: str, label: str) -> None:
    """Require one architecture marker in workflow text."""
    if fragment not in text:
        raise AssertionError(f"missing {label}: {fragment!r}")


def pinned_artifact_download_sha(text: str, label: str) -> str:
    """Require exactly one immutable official artifact-download action reference."""
    matches = re.findall(
        r"(?m)^[ \t]*uses:[ \t]*actions/download-artifact@([^\s#]+)(?:[ \t]+#[^\n]*)?$",
        text,
    )
    if len(matches) != 1 or re.fullmatch(r"[0-9a-f]{40}", matches[0]) is None:
        raise AssertionError(
            f"{label}: expected exactly one actions/download-artifact use pinned to a 40-character commit SHA"
        )
    return matches[0]


def assert_download_pin_parser_fixtures() -> None:
    """An upstream pin change is allowed; mutable, partial and ambiguous refs are not."""
    good = "      uses: actions/download-artifact@" + "a" * 40 + " # v8.0.2\n"
    if pinned_artifact_download_sha(good, "fixture") != "a" * 40:
        raise AssertionError("valid SHA pin fixture was rejected")
    for invalid in (
        "      uses: actions/download-artifact@v8.0.2\n",
        "      uses: actions/download-artifact@" + "a" * 39 + "\n",
        good + "      uses: actions/download-artifact@" + "b" * 40 + "\n",
        "",
    ):
        try:
            pinned_artifact_download_sha(invalid, "fixture")
        except AssertionError:
            continue
        raise AssertionError("invalid download action pin fixture was accepted")


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
    if "review-antigravity-candidate.yml" in text:
        raise AssertionError("scheduled upstream workflow must never dispatch the human Antigravity execution workflow")

    require(writer, "needs: antigravity-detect", "writer dependency on read-only detector")
    require(writer, "actions: write", "writer action-dispatch permission")
    require(writer, "contents: write", "writer branch-maintenance permission")
    require(writer, "pull-requests: write", "writer PR-maintenance permission")
    pinned_artifact_download_sha(writer, "scheduled writer")
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
    """Lock one human click that admits only the current validated pending candidate."""
    require(text, "group: check-upstream", "shared concurrency group")
    header = text.split("permissions:\n", 1)[0]
    require(header, "workflow_dispatch:", "manual human execution boundary")
    if "inputs:" in header:
        raise AssertionError("manual Antigravity admission must not require copy/pasted hash inputs")
    if "discover-payload" in text or "inspect-payload" in text:
        raise AssertionError("manual workflow must not retain redundant multi-stage review choices")

    candidate = job_block(text, "candidate", "maintain-pr")
    writer = job_block(text, "maintain-pr")
    require(candidate, "permissions:\n      contents: read", "read-only vendor-execution job")
    require(candidate, "fetch-depth: 0", "history needed for pending-branch ancestry gate")
    require(candidate, "persist-credentials: false", "credential-free vendor-execution checkout")
    require(candidate, 'branch="automation/update-upstreams"', "pending automation branch source")
    require(candidate, 'git fetch --no-tags origin "refs/heads/$branch:$candidate_ref"', "data-only pending branch fetch")
    require(candidate, 'git merge-base --is-ancestor "$GITHUB_SHA" "$candidate_ref"', "pending branch contains dispatched main")
    require(candidate, 'git show "$candidate_ref:third_party/antigravity-cli-detection.json"', "pending detection read as data")
    require(candidate, 'git show "$candidate_ref:third_party/antigravity-cli-candidate.json"', "pending candidate read as data")
    require(candidate, "pending detection was not generated from this main revision's reviewed baseline", "reviewed-baseline binding")
    require(candidate, "scripts/validate-antigravity-review-artifact.py", "pending metadata validation")
    require(candidate, 'echo "installer_sha256=$installer_sha" >> "$GITHUB_OUTPUT"', "validated installer job output")
    require(candidate, 'echo "payload_sha256=$payload_sha" >> "$GITHUB_OUTPUT"', "validated payload job output")
    require(candidate, "scripts/run-antigravity-inspection.py", "strict prefetch/hash inspection gate")
    if "scripts/inspect-antigravity-cli.py" in candidate:
        raise AssertionError("workflow must not invoke the legacy live downloader directly")
    if "contents: write" in candidate or "pull-requests: write" in candidate or "actions: write" in candidate:
        raise AssertionError("vendor-execution job unexpectedly gained write permission")

    require(writer, "actions: write", "writer action permission")
    require(writer, "contents: write", "writer content permission")
    require(writer, "pull-requests: write", "writer PR permission")
    pinned_artifact_download_sha(writer, "manual review writer")
    require(writer, "Revalidate artifact after crossing into the write-capable job", "post-download artifact validation")
    require(writer, '${{ needs.candidate.outputs.installer_sha256 }}', "validated installer output crosses to writer")
    require(writer, '${{ needs.candidate.outputs.payload_sha256 }}', "validated payload output crosses to writer")
    require(writer, "inspection requires the same previously validated static candidate", "mandatory static candidate gate")
    require(writer, "admitted payload does not match the pending statically discovered candidate", "exact payload admission gate")
    require(writer, 'branch="automation/update-upstreams"', "single automation branch")
    if "gh pr merge" in writer or "--auto" in writer:
        raise AssertionError("Antigravity review writer must never merge its own PR")


def main() -> None:
    """Run workflow architecture assertions."""
    upstream = UPSTREAM.read_text(encoding="utf-8")
    antigravity = ANTIGRAVITY.read_text(encoding="utf-8")
    rescan = (ROOT / ".github/workflows/rescan-published-images.yml").read_text(encoding="utf-8")
    assert_download_pin_parser_fixtures()
    assert_scheduler_contract(upstream)
    assert_antigravity_manual_contract(antigravity)
    pins = {
        pinned_artifact_download_sha(job_block(upstream, "check"), "scheduled writer"),
        pinned_artifact_download_sha(job_block(antigravity, "maintain-pr"), "manual review writer"),
        pinned_artifact_download_sha(job_block(rescan, "reconcile-alert"), "rescan writer"),
    }
    if len(pins) != 1:
        raise AssertionError("all three trust-boundary writers must pin the same artifact downloader")
    print("Optional review workflow contracts: OK")


if __name__ == "__main__":
    main()
