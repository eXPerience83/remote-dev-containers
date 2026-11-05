"""Run the real Context7 manager with isolated synthetic Codex state."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from collections.abc import Sequence


def manager_environment(
    home: Path, extra_env: dict[str, str] | None = None
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"CODEX_HOME": str(home), "REMOTE_DEV_ROLE": "codex"})
    if extra_env:
        environment.update(extra_env)
    return environment


def run_manager(
    manager: Path,
    home: Path,
    arguments: Sequence[str],
    *,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(manager), *arguments],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=manager_environment(home, extra_env),
        timeout=timeout,
        check=False,
    )


def load_module(path: Path, *, module_name: str) -> ModuleType:
    """Load one explicit Context7 source without relying on ambient Python imports."""
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
