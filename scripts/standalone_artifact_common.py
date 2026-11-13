#!/usr/bin/env python3
"""Shared, bounded input validation for standalone artifact inspection.

Kept separate from the different uv source-origin policies of the reader and
synchronizer. Every malformed shared input fails closed.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any, NoReturn


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error."""
    raise SystemExit(f"ERROR: {message}")


def read_env(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE environment file and reject duplicate keys."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"invalid environment assignment at {path}:{line_number}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            fail(f"invalid environment key at {path}:{line_number}: {key}")
        if key in values:
            fail(f"duplicate environment key in {path}: {key}")
        values[key] = value
    return values


def locked_validation_assets(values, lock_path):
    """Exactly the three PR2 Aqua artifacts, never an arbitrary backend."""
    lock = tomllib.loads(lock_path.read_text())
    result = {}
    for tool, repo, packaging in (("yq", "mikefarah/yq", "raw-binary"),
                                  ("shfmt", "mvdan/sh", "raw-binary"),
                                  ("actionlint", "rhysd/actionlint", "tar.gz")):
        version = values.get(tool.upper() + "_VERSION")
        entries = lock["tools"].get(tool, [])
        if not version or len(entries) != 1:
            fail(f"missing locked {tool}")
        entry = entries[0]
        if entry.get("version") != version or entry.get("backend") != "aqua:" + repo:
            fail(f"unreviewed locked {tool}")
        architectures = {}
        for arch, platform in (("amd64", "linux-x64"), ("arm64", "linux-arm64")):
            artifact = entry["platforms." + platform]
            asset = {"yq": f"yq_linux_{arch}", "shfmt": f"shfmt_v{version}_linux_{arch}",
                     "actionlint": f"actionlint_{version}_linux_{arch}.tar.gz"}[tool]
            url = f"https://github.com/{repo}/releases/download/v{version}/{asset}"
            if artifact.get("url") != url or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("checksum", "")):
                fail(f"unexpected {tool} {arch} artifact")
            architectures[arch] = {"asset_url": url, "asset_sha256": artifact["checksum"][7:]}
        result[tool] = {"version": version, "packaging": packaging, "architectures": architectures}
    return result


def load_report(path: Path) -> dict[str, Any]:
    """Load the inspection report as a JSON object."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid {path}: {exc}")
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        fail(f"unsupported standalone artifact inspection report: {path}")
    components = report.get("components")
    if not isinstance(components, list):
        fail(f"standalone artifact inspection report has no components array: {path}")
    return report
