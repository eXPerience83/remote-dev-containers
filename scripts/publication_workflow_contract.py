#!/usr/bin/env python3
"""Fail-closed, dependency-free contracts for our *canonical* Actions step layout.

This is deliberately NOT a general YAML parser. Publication security steps
must use the simple, unquoted canonical step keys present in our workflows.
Unknown, quoted, aliased, merged or folded keys fail review instead of being
misinterpreted by substring-based tests.
"""
from __future__ import annotations

import re

ALLOWED_KEYS = frozenset({"id", "env", "uses", "with", "run", "if"})
KEY = re.compile(r"([a-z][a-z-]*):(?: (.*))?")


def step_metadata(block: str, *, expected_if: str | None = None) -> dict[str, str]:
    """Read all 8-space step-level keys and allow only expected conditions.

    The - name marker and the block boundaries are validated by callers.
    The strict subset deliberately rejects equivalent YAML spellings,
    including "if": / 'if': and YAML merge keys.
    """
    values: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        width = len(line) - len(line.lstrip(" "))
        if width != 8:
            continue
        match = KEY.fullmatch(line.strip())
        if not match:
            raise AssertionError("non-canonical publication step YAML metadata: " +
                                 line.strip()[:90])
        key, value = match.groups()
        if key not in ALLOWED_KEYS or key in values:
            raise AssertionError("unsupported or duplicate publication step key: " + key)
        values[key] = value or ""
    if "if" in values:
        if expected_if is None or values["if"] != expected_if:
            raise AssertionError("publication step has unexpected condition: " +
                                 values["if"][:90])
    elif expected_if is not None:
        raise AssertionError("publication step lacks required condition: " + expected_if)
    if "run" in values and values["run"] != "|":
        raise AssertionError("publication run block must use literal |")
    if "continue-on-error" in block and re.search(
        r'(?m)^        (?:"continue-on-error"|' +
        r"'continue-on-error'|continue-on-error):", block
    ):
        raise AssertionError("publication step must never ignore failure")
    return values


def active_upload_paths(block: str) -> tuple[str, ...]:
    """Read only active, canonical entries inside with.path: |."""
    metadata = step_metadata(block, expected_if="always()")
    if "uses" not in metadata or "with" not in metadata:
        raise AssertionError("publication artifact upload action missing")
    lines = block.splitlines()
    markers = [i for i, line in enumerate(lines) if line == "          path: |"]
    if len(markers) != 1:
        raise AssertionError("artifact upload must define exactly one literal path list")
    output: list[str] = []
    for line in lines[markers[0] + 1:]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent < 12:
            break
        if line.lstrip().startswith("#"):
            continue
        if indent != 12 or re.fullmatch(r"[-A-Za-z0-9_./]+", line.strip()) is None:
            raise AssertionError("unexpected artifact upload path syntax")
        output.append(line.strip())
    if not output or len(set(output)) != len(output):
        raise AssertionError("artifact upload has no files or duplicates")
    return tuple(output)
