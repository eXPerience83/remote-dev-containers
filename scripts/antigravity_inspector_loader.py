#!/usr/bin/env python3
"""Load the fixed offline Antigravity inspector module for review tooling.

Do not cache or substitute the inspector: each caller retains its own freshly
loaded module, exactly as before this common-loader extraction.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def load_inspector() -> ModuleType:
    """Load the reviewed same-directory inspector or fail closed."""
    path = Path(__file__).resolve().with_name("inspect-antigravity-cli.py")
    spec = importlib.util.spec_from_file_location("antigravity_inspector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load inspect-antigravity-cli.py")
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    return inspector
