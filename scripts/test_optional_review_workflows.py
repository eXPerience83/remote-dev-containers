#!/usr/bin/env python3
"""Static regression checks for optional-tool review workflow trust boundaries."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / ".github/workflows/check-upstream.yml"
ANTIGRAVITY = ROOT / ".github/workflows/review-antigravity-candidate.yml"


def require(text: str, fragment: str, label: str) -> None:
    if fragment not in text:
        raise AssertionError(f"missing {label}: {fragment!r}")


def job_block(text: str, job: str, next_job: str | None = None) -> str:
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
    require(text, 'cron: "17 5 * * *"', "daily review cadence")
    require(text, "group: check-upstream", "shared concurrency group")
    detect = job_block(text, "antigravity-detect", "check")
    writer = job_block(text, "check")

    require(detect, "permissions:\n      contents: read", "read-only Antigravity detector")
    require(detect, "persist-credentials: false", "credential-free detector checkout")
    require(detect, "scripts/detect-antigravity-installer.py", "non-executing detector")
    require(detect, "scripts/validate-antigravity-review-artifact.py", "detector artifact validation")
    if "scripts/discover-antigravity-payload.py" in detect or "scripts/inspect-antigravity-cli.py" in detect:
        raise AssertionError("scheduled Antigravity detector must not execute admitted installer/payload stages")
    if "contents: write" in detect or "pull-requests: write" in detect or "actions: write" in detect:
        raise AssertionError("scheduled Antigravity detector unexpectedly gained write permission")

    require(writer, "needs: antigravity-detect", "writer dependency on read-only detector")
    require(writer, "actions: write", "writer action-dispatch permission")
    require(writer, "contents: write", "writer branch-maintenance permission")
    require(writer, "pull-requests: write", "writer PR-maintenance permission")
    require(writer, "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "pinned artifact download action")
    require(writer, "Revalidate detection after crossing into write-capable job", "second trust-boundary validation")
    require(writer, "https://registry.npmjs.org/ctx7/latest", "fixed Context7 registry endpoint")
    require(writer, "--max-filesize 65536", "bounded Context7 metadata transfer")
    require(writer, "scripts/update-context7-review.py", "Context7 reviewed-pin updater")
    require(writer, "scripts/test-remote-dev-context7-device-login.py", "atomic Context7 reviewed-test maintenance")
    require(writer, 'branch="automation/update-upstreams"', "single automation branch")
    if "gh pr merge" in writer or "--auto" in writer:
        raise AssertionError("upstream writer must never merge its own PR")


def assert_antigravity_manual_contract(text: str) -> None:
    require(text, "group: check-upstream", "shared concurrency group")
    require(text, "- discover-payload", "first explicit review stage")
    require(text, "- inspect-payload", "second explicit review stage")
    require(text, "installer_sha256:", "explicit installer admission input")
    require(text, "payload_sha256:", "explicit payload admission input")

    candidate = job_block(text, "candidate", "maintain-pr")
    writer = job_block(text, "maintain-pr")
    require(candidate, "permissions:\n      contents: read", "read-only vendor-byte job")
    require(candidate, "persist-credentials: false", "credential-free vendor-byte checkout")
    require(candidate, "scripts/discover-antigravity-payload.py", "payload discovery stage")
    require(candidate, "scripts/inspect-antigravity-cli.py", "full inspection stage")
    require(candidate, "scripts/validate-antigravity-review-artifact.py", "pre-upload artifact validation")
    if "contents: write" in candidate or "pull-requests: write" in candidate or "actions: write" in candidate:
        raise AssertionError("vendor-byte job unexpectedly gained write permission")

    require(writer, "actions: write", "writer action permission")
    require(writer, "contents: write", "writer content permission")
    require(writer, "pull-requests: write", "writer PR permission")
    require(writer, "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c", "pinned metadata download")
    require(writer, "Revalidate artifact after crossing into the write-capable job", "post-download artifact validation")
    require(writer, 'branch="automation/update-upstreams"', "single automation branch")
    if "gh pr merge" in writer or "--auto" in writer:
        raise AssertionError("Antigravity review writer must never merge its own PR")


def main() -> None:
    upstream = UPSTREAM.read_text(encoding="utf-8")
    antigravity = ANTIGRAVITY.read_text(encoding="utf-8")
    assert_scheduler_contract(upstream)
    assert_antigravity_manual_contract(antigravity)
    print("Optional review workflow contracts: OK")


if __name__ == "__main__":
    main()
