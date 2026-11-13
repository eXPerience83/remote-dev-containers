#!/usr/bin/env python3
"""Require Build AMD64 to cancel only superseded pull-request runs.

No GitHub API, Docker or YAML parser dependency. The expression uses one group
per PR, but each main push and workflow_dispatch has its own run identity.
"""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-amd64.yml"
GROUP = (
    "  group: build-amd64-" + "$" + "{{ github.event_name == 'pull_request' "
    "&& format('pr-{0}', github.event.pull_request.number) || github.run_id }}"
)
CANCEL = "  cancel-in-progress: " + "$" + "{{ github.event_name == 'pull_request' }}"


def validate(source: str) -> None:
    if source.count("\nconcurrency:\n") != 1:
        raise ValueError("Build AMD64 requires exactly one workflow concurrency block")
    header, rest = source.split("\nconcurrency:\n", 1)
    if "\njobs:\n" not in rest:
        raise ValueError("missing jobs after workflow concurrency")
    block, _jobs = rest.split("\njobs:\n", 1)
    if not header.startswith("name: Build AMD64\n"):
        raise ValueError("unknown Build AMD64 workflow")
    if "\npermissions:\n  contents: read\n" not in header:
        raise ValueError("workflow-level least-privilege permissions changed")
    if block.rstrip("\n").splitlines() != [GROUP, CANCEL]:
        raise ValueError("PR-only cancel policy or per-run non-PR identity changed")
    for required in (
        "on:\n  pull_request:\n  push:\n    branches: [main]\n  workflow_dispatch:\n",
        "      compare_images:\n",
    ):
        if required not in header:
            raise ValueError(f"required event trigger removed: {required!r}")


def modeled_group(event: str, run_id: int, pr_number: int | None = None) -> str:
    if event == "pull_request":
        if pr_number is None or pr_number < 1:
            raise ValueError("pull_request must have a positive PR number")
        return f"build-amd64-pr-{pr_number}"
    return f"build-amd64-{run_id}"


class ConcurrencyContract(unittest.TestCase):
    def test_workflow_has_exact_reviewed_policy(self) -> None:
        validate(WORKFLOW.read_text(encoding="utf-8"))

    def test_only_stale_runs_in_same_pr_collide(self) -> None:
        first = modeled_group("pull_request", 111, 329)
        newer = modeled_group("pull_request", 222, 329)
        other = modeled_group("pull_request", 333, 301)
        self.assertEqual(first, newer)
        self.assertNotEqual(first, other)
    def test_manual_dispatch_and_main_have_unique_run_groups(self) -> None:
        self.assertNotEqual(
            modeled_group("workflow_dispatch", 111, 329),
            modeled_group("workflow_dispatch", 222, 329),
        )
        self.assertNotEqual(
            modeled_group("push", 333),
            modeled_group("push", 444),
        )
        self.assertNotEqual(
            modeled_group("push", 111),
            modeled_group("workflow_dispatch", 222),
        )

    def test_mutations_broadening_cancellation_are_rejected(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        for old, new in (
            (CANCEL, "  cancel-in-progress: true"),
            (GROUP, "  group: build-amd64-" + "$" + "{{ github.ref }}"),
            ("    branches: [main]", "    branches: [not-main]"),
            ("  workflow_dispatch:", "  deleted_workflow_dispatch:"),
            ("  pull_request:", "  pull_request_target:"),
        ):
            with self.subTest(old=old):
                self.assertIn(old, source)
                with self.assertRaises(ValueError):
                    validate(source.replace(old, new, 1))


if __name__ == "__main__":
    unittest.main()
