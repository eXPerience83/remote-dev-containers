#!/usr/bin/env python3
"""Validate the bounded launcher/Codex Compose topology."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERIC_COMPOSE = ROOT / "compose/docker-compose.yml"
TRUENAS_COMPOSE = ROOT / "compose/truenas.yml"
LAUNCHER_AUTH_OVERRIDE = ROOT / "compose/launcher-auth.yml"
COMPOSE_FILES = (
    GENERIC_COMPOSE,
    TRUENAS_COMPOSE,
)
AUTH_COMPOSE_FILES = (
    GENERIC_COMPOSE,
    LAUNCHER_AUTH_OVERRIDE,
)
CANONICAL_IMAGE = "ghcr.io/experience83/remote-dev:edge-amd64"
FORBIDDEN_LAUNCHER_TEXT = (
    "/workspace",
    "/root/.codex",
    "/root/.config/gh",
    "/root/.config/git",
    "/root/.ssh",
    "docker.sock",
    "podman.sock",
    "/mnt/Pool1/codex/secrets/web_password.txt",
    "/run/secrets/web_password",
    "/run/secrets/launcher_password",
    "launcher_password",
    "OPENAI_API_KEY",
    "CODEX_HOME",
    "GH_CONFIG_DIR",
    "GIT_CONFIG_GLOBAL",
)
SOCKET_MARKERS = ("docker.sock", "podman.sock")


def compose_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Keep only process values needed to invoke Docker, then apply test inputs."""
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
        if key in os.environ
    }
    if overrides:
        environment.update(overrides)
    return environment


def compose_config(
    paths: Path | tuple[Path, ...],
    env_file: Path,
    overrides: dict[str, str] | None = None,
) -> dict[str, object]:
    compose_paths = (paths,) if isinstance(paths, Path) else paths
    command = ["docker", "compose", "--env-file", str(env_file)]
    for path in compose_paths:
        command.extend(("-f", str(path)))
    command.extend(("config", "--format", "json"))

    completed = subprocess.run(
        command,
        cwd=ROOT,
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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def published_targets(service: dict[str, object]) -> set[int]:
    targets: set[int] = set()
    for port in service.get("ports", []):
        if isinstance(port, dict):
            targets.add(int(port["target"]))
    return targets


def mount_sources(service: dict[str, object], target: str | None = None) -> list[str]:
    sources: list[str] = []
    for mount in service.get("volumes", []):
        if not isinstance(mount, dict):
            continue
        if target is not None and mount.get("target") != target:
            continue
        source = mount.get("source")
        if source is not None:
            sources.append(str(source))
    return sources


def service_secret_sources(service: dict[str, object], target: str) -> list[str]:
    sources: list[str] = []
    expected_name = target.removeprefix("/run/secrets/")
    for secret in service.get("secrets", []):
        if isinstance(secret, str):
            source = secret
            secret_target = secret
        elif isinstance(secret, dict):
            source_value = secret.get("source")
            if source_value is None:
                continue
            source = str(source_value)
            secret_target = str(secret.get("target", source))
        else:
            continue

        normalized_target = secret_target.removeprefix("/run/secrets/")
        if normalized_target == expected_name:
            sources.append(source)
    return sources


def credential_sources(
    config: dict[str, object],
    service: dict[str, object],
    target: str,
) -> list[str]:
    sources = [f"bind:{source}" for source in mount_sources(service, target)]
    top_level = config.get("secrets")
    for secret_name in service_secret_sources(service, target):
        require(isinstance(top_level, dict), "service secret has no top-level definition")
        secret_definition = top_level.get(secret_name)
        require(
            isinstance(secret_definition, dict),
            f"top-level secret {secret_name} is missing",
        )
        secret_file = secret_definition.get("file")
        require(secret_file is not None, f"secret {secret_name} has no file source")
        sources.append(f"secret:{secret_file}")
    return sources


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
        "WEB_PASSWORD_FILE" not in launcher_env,
        f"{path}: launcher unexpectedly requires a password file",
    )
    require(
        "WEB_PASSWORD" not in launcher_env,
        f"{path}: launcher unexpectedly renders a password",
    )
    require(
        "WEB_USERNAME" not in launcher_env,
        f"{path}: launcher unexpectedly requires a username",
    )
    require(
        codex_env.get("WEB_PASSWORD_FILE") == "/run/secrets/web_password",
        f"{path}: Codex password target",
    )
    require(
        str(launcher_env.get("ALLOW_INSECURE_WEB")) == "1",
        f"{path}: launcher should be unauthenticated by default",
    )
    require(
        str(codex_env.get("ALLOW_INSECURE_WEB")) == "0",
        f"{path}: Codex insecure default",
    )

    launcher_text = json.dumps(launcher, sort_keys=True)
    for forbidden in FORBIDDEN_LAUNCHER_TEXT:
        require(
            forbidden not in launcher_text,
            f"{path}: launcher unexpectedly contains {forbidden}",
        )

    launcher_credentials = credential_sources(
        config, launcher, "/run/secrets/launcher_password"
    )
    codex_credentials = credential_sources(config, codex, "/run/secrets/web_password")
    require(
        launcher_credentials == [],
        f"{path}: launcher must not require a credential source, got {launcher_credentials}",
    )
    require(
        len(codex_credentials) == 1,
        f"{path}: Codex must have exactly one password source, got {codex_credentials}",
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
        require(
            service.get("network_mode") != "host",
            f"{path}: {name} uses host networking",
        )
        security_opt = service.get("security_opt", [])
        require(
            "no-new-privileges:true" in security_opt,
            f"{path}: {name} lost no-new-privileges",
        )
        for source in mount_sources(service):
            lowered = source.lower()
            require(
                not any(marker in lowered for marker in SOCKET_MARKERS),
                f"{path}: {name} mounts a container-engine socket: {source}",
            )

    require(
        launcher.get("container_name") == "remote-dev-launcher",
        f"{path}: launcher container name",
    )
    require(
        codex.get("container_name") == "codex-remote-dev",
        f"{path}: Codex compatibility container name changed",
    )


def validate_auth_override_separation(env_path: Path) -> None:
    codex_relaxed = compose_config(
        GENERIC_COMPOSE,
        env_path,
        {"ALLOW_INSECURE_WEB": "1"},
    )["services"]
    require(
        str(codex_relaxed["launcher"]["environment"]["ALLOW_INSECURE_WEB"]) == "1",
        "generic Compose: Codex insecure override changed launcher default",
    )
    require(
        str(codex_relaxed["codex"]["environment"]["ALLOW_INSECURE_WEB"]) == "1",
        "generic Compose: Codex insecure override was not applied",
    )

    synthetic_secret = f"synthetic-{os.getpid()}-{os.urandom(8).hex()}"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as secret_file:
        secret_file.write(f"{synthetic_secret}\n")
        secret_file.flush()
        launcher_hardened = compose_config(
            AUTH_COMPOSE_FILES,
            env_path,
            {
                "LAUNCHER_PASSWORD_PATH": secret_file.name,
                "LAUNCHER_USERNAME": "test-launcher",
            },
        )

    rendered = json.dumps(launcher_hardened, sort_keys=True)
    require(
        synthetic_secret not in rendered,
        "generic Compose: rendered config exposed the launcher password",
    )

    services = launcher_hardened["services"]
    launcher = services["launcher"]
    codex = services["codex"]
    launcher_env = launcher["environment"]
    codex_env = codex["environment"]
    require(
        str(launcher_env["ALLOW_INSECURE_WEB"]) == "0",
        "generic Compose: launcher auth override was not applied",
    )
    require(
        launcher_env["WEB_PASSWORD_FILE"] == "/run/secrets/launcher_password",
        "generic Compose: launcher password file override was not applied",
    )
    require(
        "WEB_PASSWORD" not in launcher_env,
        "generic Compose: launcher password was rendered inline",
    )
    require(
        launcher_env["WEB_USERNAME"] == "test-launcher",
        "generic Compose: launcher username override was not applied",
    )
    require(
        len(
            credential_sources(
                launcher_hardened, launcher, "/run/secrets/launcher_password"
            )
        )
        == 1,
        "generic Compose: launcher auth override must have one file-backed secret",
    )
    require(
        str(codex_env["ALLOW_INSECURE_WEB"]) == "0",
        "generic Compose: launcher auth override leaked into Codex",
    )
    require(
        len(credential_sources(launcher_hardened, codex, "/run/secrets/web_password"))
        == 1,
        "generic Compose: launcher auth override changed the Codex password source",
    )
    require(
        mount_sources(launcher) == [],
        "generic Compose: launcher auth override added a host bind mount",
    )

    truenas_launcher = compose_config(
        TRUENAS_COMPOSE,
        env_path,
        {
            "LAUNCHER_PASSWORD_PATH": "/should/not/be/used",
            "LAUNCHER_USERNAME": "test-launcher",
        },
    )["services"]["launcher"]["environment"]
    require(
        "WEB_PASSWORD_FILE" not in truenas_launcher,
        "TrueNAS Compose: launcher password must not appear in the normal example",
    )
    require(
        "WEB_PASSWORD" not in truenas_launcher,
        "TrueNAS Compose: launcher password must not appear in the normal example",
    )
    require(
        "WEB_USERNAME" not in truenas_launcher,
        "TrueNAS Compose: launcher username must not appear in the normal example",
    )
    require(
        str(truenas_launcher["ALLOW_INSECURE_WEB"]) == "1",
        "TrueNAS Compose: launcher must remain password-free by default",
    )


def validate_truenas_password_free_source() -> None:
    launcher_source = TRUENAS_COMPOSE.read_text(encoding="utf-8").split(
        "\n  codex:", maxsplit=1
    )[0]
    for marker in (
        "LAUNCHER_PASSWORD",
        "launcher_password",
        "WEB_PASSWORD",
        "WEB_USERNAME",
    ):
        require(
            marker not in launcher_source,
            f"TrueNAS Compose launcher source unexpectedly contains {marker}",
        )


def main() -> int:
    validate_truenas_password_free_source()
    with tempfile.NamedTemporaryFile() as empty_env:
        env_path = Path(empty_env.name)
        for path in COMPOSE_FILES:
            validate(path, compose_config(path, env_path))
        validate_auth_override_separation(env_path)
    print("Single-stack image, socket, launcher and credential boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
