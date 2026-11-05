"""Render repository Compose fixtures with a bounded, explicit environment."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

_COMPOSE_ENV = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")


def compose_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    environment = {key: os.environ[key] for key in _COMPOSE_ENV if key in os.environ}
    if overrides:
        environment.update(overrides)
    return environment


def render_compose(
    root: Path,
    paths: Path | tuple[Path, ...],
    env_file: Path,
    overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    compose_paths = (paths,) if isinstance(paths, Path) else paths
    command = [
        "docker",
        "compose",
        "--profile",
        "antigravity",
        "--env-file",
        str(env_file),
    ]
    for path in compose_paths:
        command.extend(("-f", str(path)))
    command.extend(("config", "--format", "json"))
    completed = subprocess.run(
        command,
        cwd=root,
        env=compose_environment(overrides),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        rendered_paths = ", ".join(str(path) for path in compose_paths)
        raise AssertionError(
            f"docker compose config failed for {rendered_paths}:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)
