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
UBUNTU_PATTERN = (
    r"(?:# renovate: datasource=docker depName=ubuntu versioning=ubuntu\n)?"
    r"(?:ARG )?UBUNTU_VERSION=(?<currentValue>\d+\.\d+)\n"
    r"(?:ARG )?UBUNTU_DIGEST=(?<currentDigest>sha256:[a-f0-9]{64})"
)


class OwnershipError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise OwnershipError(message)


def matching_rules(config: dict[str, Any], **fields: Any) -> list[dict[str, Any]]:
    rules = config.get("packageRules")
    require(isinstance(rules, list), "packageRules must be a list")
    return [rule for rule in rules if isinstance(rule, dict) and all(rule.get(k) == v for k, v in fields.items())]


def validate_config(config: dict[str, Any]) -> None:
    require(config.get("automerge") is False, "automerge must be explicitly false")
    require(config.get("enabledManagers") == EXPECTED_MANAGERS, "enabledManagers must contain only the approved managers")

    managers = config.get("customManagers")
    require(isinstance(managers, list) and len(managers) == 1, "exactly one custom manager is allowed")
    manager = managers[0]
    require(isinstance(manager, dict), "the custom manager must be an object")
    require(manager.get("customType") == "regex", "the custom manager must be regex")
    require(manager.get("managerFilePatterns") == [r"/^(?:versions\.env|images/base/Dockerfile)$/"], "Ubuntu manager file scope changed")
    require(manager.get("matchStrings") == [UBUNTU_PATTERN], "Ubuntu manager match contract changed")
    require(manager.get("datasourceTemplate") == "docker", "Ubuntu datasource must be docker")
    require(manager.get("depNameTemplate") == "ubuntu", "Ubuntu dependency name changed")
    require(manager.get("versioningTemplate") == "ubuntu", "Ubuntu versioning must be ubuntu")

    native_exclusions = matching_rules(
        config,
        matchManagers=["dockerfile"],
        matchPackageNames=UBUNTU_NAMES,
        enabled=False,
    )
    require(len(native_exclusions) == 1, "native Dockerfile Ubuntu ownership must be disabled exactly once")

    mise_exclusions = matching_rules(config, matchManagers=["mise"], enabled=False)
    require(len(mise_exclusions) == 1, "native mise ownership must remain disabled exactly once")


def validate_repository(root: Path, config: dict[str, Any]) -> None:
    manager = config["customManagers"][0]
    python_pattern = manager["matchStrings"][0].replace("(?<currentValue>", "(?P<currentValue>").replace(
        "(?<currentDigest>", "(?P<currentDigest>"
    )
    ubuntu_matches: list[tuple[str, str]] = []
    for relative in UBUNTU_FILES:
        text = (root / relative).read_text(encoding="utf-8")
        matches = list(re.finditer(python_pattern, text))
        require(len(matches) == 1, f"Ubuntu custom manager must match {relative} exactly once")
        ubuntu_matches.append((matches[0]["currentValue"], matches[0]["currentDigest"]))
    require(len(set(ubuntu_matches)) == 1, "Ubuntu version/digest sources are not synchronized")

    dockerfile = (root / "images/base/Dockerfile").read_text(encoding="utf-8")
    require(re.search(r"^# syntax=docker/dockerfile:[^\s@]+@sha256:[a-f0-9]{64}$", dockerfile, re.MULTILINE) is not None,
            "pinned Dockerfile frontend discovery anchor is missing")

    workflows = list((root / ".github/workflows").glob("*.yml"))
    action_anchor = re.compile(r"^\s*-?\s*uses:\s+[^\s]+@[a-f0-9]{40}(?:\s+#\s+.+)?$", re.MULTILINE)
    require(any(action_anchor.search(path.read_text(encoding="utf-8")) for path in workflows),
            "pinned GitHub Actions discovery anchors are missing")


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
    print("OK: Renovate dependency ownership is bounded and synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
