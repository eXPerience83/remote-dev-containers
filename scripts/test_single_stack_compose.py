#!/usr/bin/env python3
"""Validate the bounded launcher/Codex/Antigravity Compose topology."""

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
COMPOSE_FILES = (GENERIC_COMPOSE, TRUENAS_COMPOSE)
AUTH_COMPOSE_FILES = (GENERIC_COMPOSE, LAUNCHER_AUTH_OVERRIDE)
CANONICAL_IMAGE = "ghcr.io/experience83/remote-dev:edge-amd64"
SOCKET_MARKERS = ("docker.sock", "podman.sock")
BROAD_MOUNT_PATHS = frozenset(("/", "/root", "/home", "/opt", "/usr/local"))
AGENT_CAPABILITIES = frozenset(
    ("CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETGID", "SETUID")
)
ROLE_CAPABILITIES = {
    "launcher": frozenset(("DAC_READ_SEARCH", "SETGID", "SETUID")),
    "codex": AGENT_CAPABILITIES,
    "antigravity": AGENT_CAPABILITIES,
}
ROLE_PIDS_LIMITS = {"launcher": 64, "codex": 1024, "antigravity": 1024}
ROLE_TMPFS = {
    "launcher": frozenset(
        (
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "/run:rw,nosuid,nodev,size=16m,mode=755",
        )
    ),
    "codex": frozenset(
        (
            "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777",
            "/run:rw,nosuid,nodev,size=1536m,mode=755",
        )
    ),
    "antigravity": frozenset(
        (
            "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777",
            "/run:rw,nosuid,nodev,size=64m,mode=755",
        )
    ),
}


def compose_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
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
        cwd=ROOT,
        env=compose_environment(overrides),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        rendered_paths = ", ".join(str(path) for path in compose_paths)
        raise AssertionError(f"docker compose config failed for {rendered_paths}:\n{completed.stderr}")
    return json.loads(completed.stdout)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def published_targets(service: dict[str, object]) -> set[int]:
    return {
        int(port["target"])
        for port in service.get("ports", [])
        if isinstance(port, dict)
    }


def rendered_volumes(service: dict[str, object]) -> list[dict[str, object]]:
    if "volumes" not in service:
        return []
    volumes = service["volumes"]
    require(isinstance(volumes, list), "rendered service volumes must be a list")
    for mount in volumes:
        require(isinstance(mount, dict), "rendered service volume must be a mapping")
    return volumes


def mount_sources(service: dict[str, object], target: str | None = None) -> list[str]:
    sources: list[str] = []
    for mount in rendered_volumes(service):
        if target is not None and mount.get("target") != target:
            continue
        source = mount.get("source")
        if source is not None:
            sources.append(str(source))
    return sources


def mount_targets(service: dict[str, object]) -> list[str]:
    targets: list[str] = []
    for mount in rendered_volumes(service):
        target = mount.get("target")
        if target is not None:
            targets.append(str(target))
    return targets


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
        if secret_target.removeprefix("/run/secrets/") == expected_name:
            sources.append(source)
    return sources


def credential_sources(
    config: dict[str, object], service: dict[str, object], target: str
) -> list[str]:
    sources = [f"bind:{source}" for source in mount_sources(service, target)]
    top_level = config.get("secrets")
    for secret_name in service_secret_sources(service, target):
        require(isinstance(top_level, dict), "service secret has no top-level definition")
        definition = top_level.get(secret_name)
        require(isinstance(definition, dict), f"top-level secret {secret_name} is missing")
        secret_file = definition.get("file")
        require(secret_file is not None, f"secret {secret_name} has no file source")
        sources.append(f"secret:{secret_file}")
    return sources


def validate_mount_safety(service: dict[str, object], context: str) -> None:
    for source in mount_sources(service):
        lowered = source.lower()
        require(not any(marker in lowered for marker in SOCKET_MARKERS), f"{context} engine socket {source}")
        require(source not in BROAD_MOUNT_PATHS, f"{context} broad mount source {source}")
    for target in mount_targets(service):
        lowered_target = target.lower()
        require(target not in BROAD_MOUNT_PATHS, f"{context} broad mount target {target}")
        require(not any(marker in lowered_target for marker in SOCKET_MARKERS), f"{context} engine socket target {target}")
        require("tmux" not in lowered_target, f"{context} tmux mount {target}")
        require("control" not in lowered_target, f"{context} control mount {target}")


def rendered_string_list(service: dict[str, object], key: str, context: str) -> list[str]:
    value = service.get(key)
    require(isinstance(value, list), f"{context} {key} must be a list")
    require(
        all(isinstance(item, str) for item in value),
        f"{context} {key} entries must be strings",
    )
    return value


def validate_service_hardening(
    service: dict[str, object], role: str, context: str
) -> None:
    require(service.get("user") == "0:0", f"{context} must start as root")
    require(service.get("read_only") is True, f"{context} root filesystem is writable")
    cap_drop = rendered_string_list(service, "cap_drop", context)
    require(cap_drop == ["ALL"], f"{context} cap_drop must be exactly ALL")
    cap_add = rendered_string_list(service, "cap_add", context)
    require(
        len(cap_add) == len(set(cap_add)) and frozenset(cap_add) == ROLE_CAPABILITIES[role],
        f"{context} cap_add differs from the reviewed role whitelist",
    )
    require(
        service.get("pids_limit") == ROLE_PIDS_LIMITS[role],
        f"{context} pids_limit differs from the reviewed role ceiling",
    )
    tmpfs = rendered_string_list(service, "tmpfs", context)
    require(
        len(tmpfs) == len(set(tmpfs)) and frozenset(tmpfs) == ROLE_TMPFS[role],
        f"{context} tmpfs contract differs from the reviewed role contract",
    )
    security_opt = rendered_string_list(service, "security_opt", context)
    require(
        security_opt == ["no-new-privileges:true"],
        f"{context} security options differ from no-new-privileges",
    )
    group_add = service.get("group_add", [])
    require(isinstance(group_add, list), f"{context} group_add must be a list")
    require(group_add == [], f"{context} configures supplementary groups")


def resolve_compose_file_path(path_value: str, base_file: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = base_file.parent / path
    return path.resolve()


def validate(path: Path, config: dict[str, object]) -> None:
    services = config.get("services")
    require(isinstance(services, dict), f"{path}: services missing")
    require(set(services) == {"launcher", "codex", "antigravity"}, f"{path}: unexpected services")
    launcher = services["launcher"]
    codex = services["codex"]
    antigravity = services["antigravity"]
    for name, service in services.items():
        require(isinstance(service, dict), f"{path}: invalid {name} service")
        require(service.get("image") == CANONICAL_IMAGE, f"{path}: {name} image")
    require(len({service["image"] for service in services.values()}) == 1, f"{path}: image mismatch")

    launcher_env = launcher.get("environment")
    codex_env = codex.get("environment")
    antigravity_env = antigravity.get("environment")
    require(isinstance(launcher_env, dict), f"{path}: launcher environment")
    require(isinstance(codex_env, dict), f"{path}: Codex environment")
    require(isinstance(antigravity_env, dict), f"{path}: Antigravity environment")
    require(launcher_env.get("REMOTE_DEV_ROLE") == "launcher", f"{path}: launcher role")
    require(codex_env.get("REMOTE_DEV_ROLE") == "codex", f"{path}: Codex role")
    require(antigravity_env.get("REMOTE_DEV_ROLE") == "antigravity", f"{path}: Antigravity role")
    require("REMOTE_DEV_PROJECT" not in launcher_env, f"{path}: launcher received project selector")
    require(codex_env.get("REMOTE_DEV_PROJECT") == "", f"{path}: Codex project selector default")
    require(antigravity_env.get("REMOTE_DEV_PROJECT") == "", f"{path}: Antigravity project selector default")
    require(str(antigravity_env.get("REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY")) == "1", f"{path}: Antigravity gate")
    require(str(antigravity_env.get("AGY_CLI_DISABLE_AUTO_UPDATE")).lower() == "true", f"{path}: auto update")

    for key in ("WEB_PASSWORD_FILE", "WEB_PASSWORD", "WEB_USERNAME"):
        require(key not in launcher_env, f"{path}: launcher unexpectedly contains {key}")

    for name, environment in (("Codex", codex_env), ("Antigravity", antigravity_env)):
        require(str(environment.get("ALLOW_INSECURE_WEB")) == "0", f"{path}: {name} authentication")
        if path == TRUENAS_COMPOSE:
            require("WEB_PASSWORD_FILE" not in environment, f"{path}: {name} still uses password file")
            require(
                environment.get("WEB_PASSWORD") == "",
                f"{path}: {name} public YAML password must remain empty",
            )
        else:
            require(environment.get("WEB_PASSWORD_FILE") == "/run/secrets/web_password", f"{path}: {name} password target")
            require("WEB_PASSWORD" not in environment, f"{path}: {name} generic password leaked into environment")
        require(
            environment.get("NPM_CONFIG_CACHE") == "/tmp/remote-dev-npm-cache",
            f"{path}: {name} transient npm cache",
        )
        require(
            environment.get("UV_CACHE_DIR") == "/tmp/remote-dev-uv-cache",
            f"{path}: {name} transient uv cache",
        )

    require(str(launcher_env.get("ALLOW_INSECURE_WEB")) == "1", f"{path}: launcher auth")

    expected_enabled = "1" if path == TRUENAS_COMPOSE else "0"
    require(
        str(launcher_env.get("REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED")) == expected_enabled,
        f"{path}: Antigravity launcher opt-in",
    )
    require(int(launcher_env.get("REMOTE_DEV_LAUNCHER_CODEX_PORT")) == 7681, f"{path}: Codex route")
    require(int(launcher_env.get("REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PORT")) == 7682, f"{path}: Antigravity route")

    launcher_text = json.dumps(launcher, sort_keys=True)
    for forbidden in (
        "/workspace",
        "/root/.codex",
        "/root/.config/gh",
        "/root/.config/git",
        "/root/.ssh",
        "/root/.local/bin",
        "/root/.gemini",
        "docker.sock",
        "podman.sock",
        "/run/secrets/web_password",
        "OPENAI_API_KEY",
        "CODEX_HOME",
        "GH_CONFIG_DIR",
        "GIT_CONFIG_GLOBAL",
        "REMOTE_DEV_PROJECT",
    ):
        require(forbidden not in launcher_text, f"{path}: launcher contains {forbidden}")

    require(mount_sources(launcher) == [], f"{path}: launcher must remain mount-free")
    codex_credentials = credential_sources(config, codex, "/run/secrets/web_password")
    antigravity_credentials = credential_sources(config, antigravity, "/run/secrets/web_password")
    if path == TRUENAS_COMPOSE:
        require(codex_credentials == [], f"{path}: Codex retained file credentials")
        require(antigravity_credentials == [], f"{path}: Antigravity retained file credentials")
    else:
        require(len(codex_credentials) == 1, f"{path}: Codex credentials {codex_credentials}")
        require(len(antigravity_credentials) == 1, f"{path}: Antigravity credentials {antigravity_credentials}")
        require(codex_credentials != antigravity_credentials, f"{path}: shared terminal credential source")

    require(published_targets(launcher) == {7680}, f"{path}: launcher ports")
    require(published_targets(codex) == {7681}, f"{path}: Codex ports")
    require(published_targets(antigravity) == {7682}, f"{path}: Antigravity ports")

    codex_sources = set(mount_sources(codex))
    antigravity_sources = set(mount_sources(antigravity))
    require(codex_sources.isdisjoint(antigravity_sources), f"{path}: agents share host paths")

    for name, service in services.items():
        require(service.get("privileged", False) is False, f"{path}: {name} privileged")
        network_mode = service.get("network_mode")
        require(
            network_mode is None or isinstance(network_mode, str),
            f"{path}: {name} network mode shape",
        )
        require(network_mode != "host", f"{path}: {name} host network")
        pid_mode = service.get("pid")
        require(
            pid_mode is None or isinstance(pid_mode, str),
            f"{path}: {name} PID mode shape",
        )
        require(pid_mode != "host", f"{path}: {name} host PID namespace")
        validate_service_hardening(service, name, f"{path}: {name}")
        environment = service.get("environment")
        require(isinstance(environment, dict), f"{path}: {name} environment")
        require("REMOTE_DEV_DATA_ROOT" not in environment, f"{path}: {name} received parent data root")
        validate_mount_safety(service, f"{path}: {name}")

    require(launcher.get("container_name") == "remote-dev-launcher", f"{path}: launcher name")
    require(codex.get("container_name") == "codex-remote-dev", f"{path}: Codex name")
    require(antigravity.get("container_name") == "antigravity-remote-dev", f"{path}: Antigravity name")
    if path == GENERIC_COMPOSE:
        require(antigravity.get("profiles") == ["antigravity"], f"{path}: Antigravity profile")


def validate_direct_project_override(env_path: Path) -> None:
    override = {"REMOTE_DEV_PROJECT": "project-alpha"}

    rendered = compose_config(GENERIC_COMPOSE, env_path, override)
    services = rendered["services"]
    launcher_env = services["launcher"]["environment"]
    codex_env = services["codex"]["environment"]
    antigravity_env = services["antigravity"]["environment"]
    require("REMOTE_DEV_PROJECT" not in launcher_env, "project selector leaked into generic launcher")
    require(
        "project-alpha" not in json.dumps(services["launcher"], sort_keys=True),
        "project selector value leaked into generic launcher service",
    )
    require(codex_env.get("REMOTE_DEV_PROJECT") == "project-alpha", "Codex project override missing")
    require(
        antigravity_env.get("REMOTE_DEV_PROJECT") == "project-alpha",
        "Antigravity project override missing",
    )

    # The TrueNAS reference YAML is edited directly; ambient/.env overrides must not rewrite its literal selector.
    rendered = compose_config(TRUENAS_COMPOSE, env_path, override)
    services = rendered["services"]
    launcher_env = services["launcher"]["environment"]
    codex_env = services["codex"]["environment"]
    antigravity_env = services["antigravity"]["environment"]
    require("REMOTE_DEV_PROJECT" not in launcher_env, "project selector leaked into TrueNAS launcher")
    require(
        "project-alpha" not in json.dumps(services["launcher"], sort_keys=True),
        "ambient project selector value leaked into TrueNAS launcher service",
    )
    require(codex_env.get("REMOTE_DEV_PROJECT") == "", "TrueNAS Codex selector must remain YAML-controlled")
    require(
        antigravity_env.get("REMOTE_DEV_PROJECT") == "",
        "TrueNAS Antigravity selector must remain YAML-controlled",
    )


def validate_auth_override_separation(env_path: Path) -> None:
    relaxed = compose_config(GENERIC_COMPOSE, env_path, {"ALLOW_INSECURE_WEB": "1"})["services"]
    require(str(relaxed["launcher"]["environment"]["ALLOW_INSECURE_WEB"]) == "1", "launcher changed")
    require(str(relaxed["codex"]["environment"]["ALLOW_INSECURE_WEB"]) == "1", "Codex override missing")
    require(str(relaxed["antigravity"]["environment"]["ALLOW_INSECURE_WEB"]) == "0", "Codex auth leaked")

    default_auth = compose_config(AUTH_COMPOSE_FILES, env_path, {"LAUNCHER_USERNAME": "test-launcher"})
    launcher = default_auth["services"]["launcher"]
    sources = credential_sources(default_auth, launcher, "/run/secrets/launcher_password")
    require(len(sources) == 1 and sources[0].startswith("secret:"), "launcher auth must be file-backed")
    default_path = resolve_compose_file_path(sources[0].removeprefix("secret:"), GENERIC_COMPOSE)
    require(default_path == (ROOT / "secrets/launcher_password.txt").resolve(), "launcher secret path")

    synthetic = f"synthetic-{os.getpid()}-{os.urandom(8).hex()}"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as secret_file:
        secret_file.write(f"{synthetic}\n")
        secret_file.flush()
        hardened = compose_config(
            AUTH_COMPOSE_FILES,
            env_path,
            {"LAUNCHER_PASSWORD_PATH": secret_file.name, "LAUNCHER_USERNAME": "test-launcher"},
        )
    require(synthetic not in json.dumps(hardened, sort_keys=True), "rendered password leak")
    launcher = hardened["services"]["launcher"]
    validate_service_hardening(launcher, "launcher", "launcher auth override")
    require(str(launcher["environment"]["ALLOW_INSECURE_WEB"]) == "0", "launcher auth override")
    require(launcher["environment"]["WEB_PASSWORD_FILE"] == "/run/secrets/launcher_password", "launcher password target")
    require(mount_sources(launcher) == [], "launcher auth added a bind mount")


def validate_truenas_launcher_password_free_source() -> None:
    launcher_source = TRUENAS_COMPOSE.read_text(encoding="utf-8").split("\n  codex:", maxsplit=1)[0]
    for marker in ("LAUNCHER_PASSWORD", "launcher_password", "WEB_PASSWORD", "WEB_USERNAME"):
        require(marker not in launcher_source, f"TrueNAS launcher source contains {marker}")


def validate_rendered_volume_shapes() -> None:
    for volumes in (["../data:/root/.ssh"], {"source": "../data", "target": "/root/.ssh"}):
        for validator in (mount_sources, mount_targets):
            try:
                validator({"volumes": volumes})
            except AssertionError:
                continue
            raise AssertionError(f"invalid rendered volume shape was accepted: {volumes!r}")
    try:
        validate_mount_safety({"volumes": [{"source": "/", "target": "/workspace"}]}, "regression")
    except AssertionError:
        pass
    else:
        raise AssertionError("broad rendered volume source was accepted")


def main() -> int:
    validate_rendered_volume_shapes()
    validate_truenas_launcher_password_free_source()
    with tempfile.NamedTemporaryFile() as empty_env:
        env_path = Path(empty_env.name)
        for path in COMPOSE_FILES:
            validate(path, compose_config(path, env_path))
        validate_direct_project_override(env_path)
        validate_auth_override_separation(env_path)
    print("Single-stack image, socket, launcher, credential and project-selector boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
