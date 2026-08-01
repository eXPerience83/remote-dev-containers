#!/usr/bin/env python3
"""Validate the bounded launcher/Codex Compose topology."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = (
    ROOT / "compose/docker-compose.yml",
    ROOT / "compose/truenas.yml",
)
CANONICAL_IMAGE = "ghcr.io/experience83/remote-dev:edge-amd64"
FORBIDDEN_LAUNCHER_TEXT = (
    "/workspace",
    "/root/.codex",
    "/root/.config/gh",
    "/root/.config/git",
    "/root/.ssh",
    "/var/run/docker.sock",
    "/mnt/Pool1/codex/secrets/web_password.txt",
    "/run/secrets/web_password",
    "OPENAI_API_KEY",
    "CODEX_HOME",
    "GH_CONFIG_DIR",
    "GIT_CONFIG_GLOBAL",
)


def compose_config(path: Path, env_file: Path) -> dict[str, object]:
    env = os.environ.copy()
    env.pop("REMOTE_DEV_IMAGE", None)
    env.pop("CODEX_IMAGE", None)
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(path),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"docker compose config failed for {path}:\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def published_targets(service: dict[str, object]) -> set[int]:
    targets: set[int] = set()
    for port in service.get("ports", []):
        if isinstance(port, dict):
            targets.add(int(port["target"]))
    return targets


def mount_source(service: dict[str, object], target: str) -> str | None:
    for mount in service.get("volumes", []):
        if isinstance(mount, dict) and mount.get("target") == target:
            source = mount.get("source")
            return str(source) if source is not None else None
    return None


def validate(path: Path, config: dict[str, object]) -> None:
    services = config.get("services")
    require(isinstance(services, dict), f"{path}: services missing")
    require(set(services) == {"launcher", "codex"}, f"{path}: unexpected services")

    launcher = services["launcher"]
    codex = services["codex"]
    require(isinstance(launcher, dict), f"{path}: invalid launcher service")
    require(isinstance(codex, dict), f"{path}: invalid codex service")

    require(launcher.get("image") == CANONICAL_IMAGE, f"{path}: launcher image")
    require(codex.get("image") == CANONICAL_IMAGE, f"{path}: codex image")
    require(
        launcher.get("image") == codex.get("image"),
        f"{path}: services do not share one image reference",
    )

    launcher_env = launcher.get("environment")
    codex_env = codex.get("environment")
    require(isinstance(launcher_env, dict), f"{path}: launcher environment")
    require(isinstance(codex_env, dict), f"{path}: codex environment")
    require(
        launcher_env.get("REMOTE_DEV_ROLE") == "launcher",
        f"{path}: launcher role",
    )
    require(codex_env.get("REMOTE_DEV_ROLE") == "codex", f"{path}: codex role")
    require(
        launcher_env.get("REMOTE_DEV_START_MODE") == "menu",
        f"{path}: launcher start mode",
    )
    require(
        launcher_env.get("WEB_PASSWORD_FILE") == "/run/secrets/launcher_password",
        f"{path}: launcher password target",
    )
    require(
        codex_env.get("WEB_PASSWORD_FILE") == "/run/secrets/web_password",
        f"{path}: Codex password target",
    )
    require(
        launcher_env.get("WEB_PASSWORD_FILE") != codex_env.get("WEB_PASSWORD_FILE"),
        f"{path}: launcher and Codex share a credential target",
    )

    launcher_text = json.dumps(launcher, sort_keys=True)
    for forbidden in FORBIDDEN_LAUNCHER_TEXT:
        require(
            forbidden not in launcher_text,
            f"{path}: launcher unexpectedly contains {forbidden}",
        )

    top_level_secrets = config.get("secrets")
    if isinstance(top_level_secrets, dict):
        launcher_secret = top_level_secrets.get("launcher_password")
        codex_secret = top_level_secrets.get("web_password")
        require(isinstance(launcher_secret, dict), f"{path}: launcher secret missing")
        require(isinstance(codex_secret, dict), f"{path}: Codex secret missing")
        require(
            launcher_secret.get("file") != codex_secret.get("file"),
            f"{path}: launcher and Codex secret files must be independent",
        )

    launcher_mount = mount_source(launcher, "/run/secrets/launcher_password")
    codex_mount = mount_source(codex, "/run/secrets/web_password")
    if launcher_mount is not None:
        require(codex_mount is not None, f"{path}: Codex password mount missing")
        require(
            launcher_mount != codex_mount,
            f"{path}: launcher and Codex bind the same password source",
        )

    require(
        published_targets(launcher) == {7680},
        f"{path}: launcher must publish only container port 7680",
    )
    require(
        published_targets(codex) == {7681},
        f"{path}: Codex must publish only container port 7681",
    )

    for name, service in (("launcher", launcher), ("codex", codex)):
        require(service.get("privileged") is not True, f"{path}: {name} privileged")
        require(not service.get("cap_add"), f"{path}: {name} adds capabilities")
        security_opt = service.get("security_opt", [])
        require(
            "no-new-privileges:true" in security_opt,
            f"{path}: {name} lost no-new-privileges",
        )

    require(
        launcher.get("container_name") == "remote-dev-launcher",
        f"{path}: launcher container name",
    )
    require(
        codex.get("container_name") == "codex-remote-dev",
        f"{path}: Codex compatibility container name changed",
    )


def main() -> int:
    with tempfile.NamedTemporaryFile() as empty_env:
        env_path = Path(empty_env.name)
        for path in COMPOSE_FILES:
            validate(path, compose_config(path, env_path))
    print("Single-stack image, launcher mounts and credential boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
