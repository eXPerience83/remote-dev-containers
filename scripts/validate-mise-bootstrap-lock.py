#!/usr/bin/env python3
"""Validate the isolated Python-only bootstrap lock before any mise install.

The generated bootstrap lock is disposable. Keep the committed full project
lock at its reviewed format until a separately reviewed migration.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import tomllib
from pathlib import Path

SUPPORTED_BOOTSTRAP_FORMATS = frozenset({3, 4})
PYTHON_VERSION_RE = re.compile(r"^3\\.(?:14|15)\\.[0-9]+$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--python-version", required=True)
    args = parser.parse_args()

    if not PYTHON_VERSION_RE.fullmatch(args.python_version):
        parser.error("expected an exact supported Python 3.14/3.15 patch")

    validator_path = Path(__file__).resolve().with_name("validate-mise-lock.py")
    spec = importlib.util.spec_from_file_location("mise_lock_validator", validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the reviewed mise lock validator")
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    try:
        with args.lock.open("rb") as source:
            lock = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        validator.fail(f"cannot read bootstrap mise.lock: {exc}")

    validator.require_exact_keys(lock, {"lockfile_version", "tools"}, "bootstrap lock")
    version = lock.get("lockfile_version")
    if type(version) is not int or version not in SUPPORTED_BOOTSTRAP_FORMATS:
        validator.fail(
            "bootstrap mise.lock format is not reviewed (expected version 3 or 4): "
            f"{version!r}"
        )
    tools = lock.get("tools")
    if not isinstance(tools, dict):
        validator.fail("bootstrap mise.lock must have a tools mapping")
    validator.require_exact_keys(tools, {"python"}, "bootstrap tools")
    validator.validate_tool_entry("python", args.python_version, tools["python"])
    print(f"Validated isolated Python bootstrap lock format {version} for both platforms.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
