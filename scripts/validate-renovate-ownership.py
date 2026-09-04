#!/usr/bin/env python3
"""Validate the repository's bounded Renovate dependency ownership contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EXPECTED_MANAGERS = ["dockerfile", "github-actions", "custom.regex"]
UBUNTU_NAMES = ["ubuntu", "docker.io/library/ubuntu"]
UBUNTU_FILES = ["versions.env", "images/base/Dockerfile"]
UBUNTU_FROM = "FROM ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}"
DOCKERFILE_FRONTEND_PACKAGE = "docker/dockerfile"
DOCKERFILE_DEFAULT_DENY = {
    "description": "Deny native Dockerfile ownership unless a later repository rule explicitly allows it",
    "matchManagers": ["dockerfile"],
    "enabled": False,
}
DOCKERFILE_FRONTEND_ALLOW = {
    "description": "Allow only the pinned Dockerfile frontend through the native Dockerfile manager",
    "matchManagers": ["dockerfile"],
    "matchPackageNames": [DOCKERFILE_FRONTEND_PACKAGE],
    "enabled": True,
}
TERMINAL_AUTOMERGE_GUARD = {
    "description": "Repository policy requires human merge review for every Renovate dependency",
    "matchPackageNames": ["*"],
    "automerge": False,
}
UBUNTU_PATTERN = (
    r"(?:# renovate: datasource=docker depName=ubuntu versioning=ubuntu\n)?"
    r"(?:ARG )?UBUNTU_VERSION=(?<currentValue>\d+\.\d+)\n"
    r"(?:ARG )?UBUNTU_DIGEST=(?<currentDigest>sha256:[a-f0-9]{64})"
)
UBUNTU_CHANGELOG_PATTERN = (
    r"<!-- remote-dev-renovate-ubuntu: datasource=docker depName=ubuntu versioning=ubuntu "
    r"UBUNTU_VERSION=(?<currentValue>\d+\.\d+) "
    r"UBUNTU_DIGEST=(?<currentDigest>sha256:[a-f0-9]{64}) -->"
)
UBUNTU_CHANGELOG_TEMPLATE = (
    "- Ubuntu LTS base {{{currentValue}}}@{{{currentDigest}}} → "
    "{{{newValue}}}@{{{newDigest}}}.\n"
    "<!-- remote-dev-renovate-ubuntu: datasource=docker depName=ubuntu versioning=ubuntu "
    "UBUNTU_VERSION={{{newValue}}} UBUNTU_DIGEST={{{newDigest}}} -->"
)
UBUNTU_CHANGELOG_HEADING = "### Renovate image refreshes"
UBUNTU_CHANGELOG_START = "<!-- remote-dev-renovate-runtime-refreshes:start -->"
UBUNTU_CHANGELOG_END = "<!-- remote-dev-renovate-runtime-refreshes:end -->"
UBUNTU_SOURCE_MANAGER = {
    "customType": "regex",
    "description": "Keep the Ubuntu LTS tag and immutable digest synchronized between versions.env and the base Dockerfile",
    "managerFilePatterns": [r"/^(?:versions\.env|images/base/Dockerfile)$/"],
    "matchStrings": [UBUNTU_PATTERN],
    "datasourceTemplate": "docker",
    "depNameTemplate": "ubuntu",
    "versioningTemplate": "ubuntu",
}
UBUNTU_CHANGELOG_MANAGER = {
    "customType": "regex",
    "description": "Append bounded Ubuntu base-image provenance inside the Renovate-owned Unreleased changelog block",
    "managerFilePatterns": [r"/^CHANGELOG\.md$/"],
    "matchStrings": [UBUNTU_CHANGELOG_PATTERN],
    "autoReplaceStringTemplate": UBUNTU_CHANGELOG_TEMPLATE,
    "datasourceTemplate": "docker",
    "depNameTemplate": "ubuntu",
    "versioningTemplate": "ubuntu",
}


class OwnershipError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OwnershipError(message)


def matching_rules(config: dict[str, Any], **fields: Any) -> list[dict[str, Any]]:
    rules = config.get("packageRules")
    require(isinstance(rules, list), "packageRules must be a list")
    return [rule for rule in rules if isinstance(rule, dict) and all(rule.get(k) == v for k, v in fields.items())]


def python_regex(pattern: str) -> str:
    return pattern.replace("(?<currentValue>", "(?P<currentValue>").replace(
        "(?<currentDigest>", "(?P<currentDigest>"
    )


def validate_config(config: dict[str, Any]) -> None:
    require(config.get("automerge") is False, "automerge must be explicitly false")
    require(config.get("enabledManagers") == EXPECTED_MANAGERS, "enabledManagers must contain only the approved managers")

    managers = config.get("customManagers")
    require(
        managers == [UBUNTU_SOURCE_MANAGER, UBUNTU_CHANGELOG_MANAGER],
        "customManagers must contain only the exact Ubuntu source and bounded changelog managers",
    )

    mise_exclusions = matching_rules(config, matchManagers=["mise"], enabled=False)
    require(len(mise_exclusions) == 1, "native mise ownership must remain disabled exactly once")

    rules = config.get("packageRules")
    require(isinstance(rules, list) and len(rules) > 0, "packageRules must be a non-empty list")

    default_deny_indexes = [
        index
        for index, rule in enumerate(rules)
        if isinstance(rule, dict) and rule == DOCKERFILE_DEFAULT_DENY
    ]
    require(len(default_deny_indexes) == 1, "native Dockerfile ownership must be denied by default exactly once")

    frontend_allow_indexes = [
        index
        for index, rule in enumerate(rules)
        if isinstance(rule, dict) and rule == DOCKERFILE_FRONTEND_ALLOW
    ]
    require(len(frontend_allow_indexes) == 1, "the pinned Dockerfile frontend must be explicitly enabled exactly once")
    require(
        default_deny_indexes[0] < frontend_allow_indexes[0],
        "the native Dockerfile default-deny rule must precede the frontend allow rule",
    )

    for rule in rules:
        if not isinstance(rule, dict) or rule.get("enabled") is not True:
            continue
        require(
            rule == DOCKERFILE_FRONTEND_ALLOW,
            "only the pinned Dockerfile frontend may be explicitly enabled",
        )

    ubuntu_groups = [
        rule
        for rule in rules
        if isinstance(rule, dict)
        and rule.get("matchDatasources") == ["docker"]
        and rule.get("matchPackageNames") == UBUNTU_NAMES
    ]
    require(len(ubuntu_groups) == 1, "Ubuntu LTS grouping rule must exist exactly once")
    require(ubuntu_groups[0].get("groupName") == "Ubuntu LTS base", "Ubuntu updates must remain in one grouped PR")
    require(ubuntu_groups[0].get("versioning") == "ubuntu", "Ubuntu package rule versioning changed")
    require(
        ubuntu_groups[0].get("allowedVersions") == r"/^(?:[0-9]*[02468])\.04$/",
        "Ubuntu package rule must remain limited to LTS tags",
    )

    require(
        all(rule.get("automerge") is not True for rule in rules if isinstance(rule, dict)),
        "no packageRule may enable automerge",
    )
    require(
        isinstance(rules[-1], dict) and rules[-1] == TERMINAL_AUTOMERGE_GUARD,
        "the terminal match-all no-automerge guard must be the final package rule",
    )


def validate_repository(root: Path, config: dict[str, Any]) -> None:
    source_manager = config["customManagers"][0]
    source_pattern = python_regex(source_manager["matchStrings"][0])
    ubuntu_matches: list[tuple[str, str]] = []
    for relative in UBUNTU_FILES:
        text = (root / relative).read_text(encoding="utf-8")
        matches = list(re.finditer(source_pattern, text))
        require(len(matches) == 1, f"Ubuntu custom manager must match {relative} exactly once")
        ubuntu_matches.append((matches[0]["currentValue"], matches[0]["currentDigest"]))
    require(len(set(ubuntu_matches)) == 1, "Ubuntu version/digest sources are not synchronized")
    ubuntu_pair = ubuntu_matches[0]

    dockerfile = (root / "images/base/Dockerfile").read_text(encoding="utf-8")
    require(
        dockerfile.splitlines().count(UBUNTU_FROM) == 1,
        "the synchronized Ubuntu base-image consumer must appear exactly once",
    )
    require(
        re.search(r"^# syntax=docker/dockerfile:[^\s@]+@sha256:[a-f0-9]{64}$", dockerfile, re.MULTILINE) is not None,
        "pinned Dockerfile frontend discovery anchor is missing",
    )

    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    changelog_pattern = python_regex(config["customManagers"][1]["matchStrings"][0])
    changelog_matches = list(re.finditer(changelog_pattern, changelog))
    require(len(changelog_matches) == 1, "Renovate Ubuntu changelog state anchor must match exactly once")
    changelog_pair = (changelog_matches[0]["currentValue"], changelog_matches[0]["currentDigest"])
    require(changelog_pair == ubuntu_pair, "Renovate changelog Ubuntu state is not synchronized with the runtime pins")

    require(changelog.count(UBUNTU_CHANGELOG_HEADING) == 1, "Renovate image refresh heading must appear exactly once")
    require(changelog.count(UBUNTU_CHANGELOG_START) == 1, "Renovate changelog start marker must appear exactly once")
    require(changelog.count(UBUNTU_CHANGELOG_END) == 1, "Renovate changelog end marker must appear exactly once")
    require(changelog.count("## [Unreleased]") == 1, "Unreleased changelog heading must appear exactly once")
    require(changelog.count("### Added") == 1, "Added changelog heading must appear exactly once")

    unreleased_index = changelog.index("## [Unreleased]")
    heading_index = changelog.index(UBUNTU_CHANGELOG_HEADING)
    start_index = changelog.index(UBUNTU_CHANGELOG_START)
    anchor_index = changelog_matches[0].start()
    end_index = changelog.index(UBUNTU_CHANGELOG_END)
    added_index = changelog.index("### Added")
    require(
        unreleased_index < heading_index < start_index < anchor_index < end_index < added_index,
        "Renovate Ubuntu changelog state escaped its machine-owned Unreleased boundary",
    )

    workflows = list((root / ".github/workflows").glob("*.yml"))
    action_anchor = re.compile(r"^\s*-?\s*uses:\s+[^\s]+@[a-f0-9]{40}(?:\s+#\s+.+)?$", re.MULTILINE)
    require(
        any(action_anchor.search(path.read_text(encoding="utf-8")) for path in workflows),
        "pinned GitHub Actions discovery anchors are missing",
    )


def validate(root: Path) -> None:
    config = json.loads((root / "renovate.json").read_text(encoding="utf-8"))
    require(isinstance(config, dict), "renovate.json must contain an object")
    validate_config(config)
    validate_repository(root, config)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        validate(args.root.resolve())
    except (OwnershipError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: Renovate ownership validation failed: {exc}")
        return 1
    print("OK: Renovate dependency ownership and runtime changelog provenance are bounded and synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
