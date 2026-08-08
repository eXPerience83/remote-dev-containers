#!/usr/bin/env python3
"""Validate the canonical role-scoped Remote Dev persistent-data contract."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERIC_COMPOSE = ROOT / "compose/docker-compose.yml"
TRUENAS_COMPOSE = ROOT / "compose/truenas.yml"
ENV_EXAMPLE = ROOT / ".env.example"
PREFLIGHT = ROOT / "scripts/preflight-data-layout.py"
TRUENAS_ROOT = "/mnt/Pool1/remote-dev"
CODEX_RUNTIME_TARGET = "/root/.local/share/remote-dev/codex-runtime"

EXPECTED_TARGET_SUFFIXES = {
    "codex": {
        "/workspace": "/workspaces/codex",
        "/root/.codex": "/state/codex/agent",
        CODEX_RUNTIME_TARGET: "/state/codex/runtime",
        "/root/.config/gh": "/state/codex/gh",
        "/root/.config/git": "/state/codex/git",
        "/root/.ssh": "/state/codex/ssh",
    },
    "antigravity": {
        "/workspace": "/workspaces/antigravity",
        "/root/.local/bin": "/state/antigravity/bin",
        "/root/.local/share/remote-dev/antigravity": "/state/antigravity/runtime",
        "/root/.gemini/antigravity-cli": "/state/antigravity/vendor",
        "/root/.config/gh": "/state/antigravity/gh",
        "/root/.config/git": "/state/antigravity/git",
        "/root/.ssh": "/state/antigravity/ssh",
    },
}
ANTIGRAVITY_PASSWORD_SUFFIX = "/secrets/antigravity/web_password.txt"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def compose_environment() -> dict[str, str]:
    return {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
        if key in os.environ
    }


def compose_config(path: Path) -> dict[str, object]:
    with tempfile.NamedTemporaryFile() as empty_env:
        completed = subprocess.run(
            [
                "docker",
                "compose",
                "--profile",
                "antigravity",
                "--env-file",
                empty_env.name,
                "-f",
                str(path),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=compose_environment(),
            text=True,
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(f"docker compose config failed for {path}:\n{completed.stderr}")
    return json.loads(completed.stdout)


def volume_map(service: dict[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for mount in service.get("volumes", []):
        require(isinstance(mount, dict), "rendered volume must use long syntax")
        target = mount.get("target")
        require(isinstance(target, str), "rendered volume is missing a target")
        require(target not in result, f"duplicate mount target: {target}")
        result[target] = mount
    return result


def validate_bind_mount(path: Path, mount: dict[str, object], suffix: str) -> None:
    source = mount.get("source")
    require(isinstance(source, str), f"{path}: bind mount source is missing")
    require(source.endswith(suffix), f"{path}: unexpected source {source} for {suffix}")
    require(mount.get("type") == "bind", f"{path}: {source} is not a bind mount")
    bind = mount.get("bind")
    require(isinstance(bind, dict), f"{path}: {source} has no bind options")
    require(
        bind.get("create_host_path") is not True,
        f"{path}: {source} explicitly enables automatic host-path creation",
    )


def validate_compose(path: Path, *, truenas: bool) -> None:
    config = compose_config(path)
    services = config.get("services")
    require(isinstance(services, dict), f"{path}: services missing")
    require(set(services) == {"launcher", "codex", "antigravity"}, f"{path}: unexpected services")
    require(volume_map(services["launcher"]) == {}, f"{path}: launcher must remain mount-free")

    all_sources: dict[str, set[str]] = {}
    for role in ("codex", "antigravity"):
        service = services[role]
        require(isinstance(service, dict), f"{path}: invalid {role} service")
        mounts = volume_map(service)
        expected_targets = set(EXPECTED_TARGET_SUFFIXES[role])
        if not truenas and role == "antigravity":
            expected_targets.add("/run/secrets/web_password")
        require(
            set(mounts) == expected_targets,
            f"{path}: unexpected {role} mount targets: {sorted(mounts)}",
        )

        sources: set[str] = set()
        for target, suffix in EXPECTED_TARGET_SUFFIXES[role].items():
            mount = mounts[target]
            validate_bind_mount(path, mount, suffix)
            source = str(mount["source"])
            sources.add(source)
            if truenas:
                require(source == f"{TRUENAS_ROOT}{suffix}", f"{path}: invalid TrueNAS source {source}")

        if not truenas and role == "antigravity":
            password_mount = mounts["/run/secrets/web_password"]
            validate_bind_mount(path, password_mount, ANTIGRAVITY_PASSWORD_SUFFIX)
            require(password_mount.get("read_only") is True, f"{path}: Antigravity password must be read-only")
            sources.add(str(password_mount["source"]))
        all_sources[role] = sources

        environment = service.get("environment")
        require(isinstance(environment, dict), f"{path}: {role} environment missing")
        if role == "codex":
            require(
                environment.get("REMOTE_DEV_CODEX_RUNTIME_ROOT") == CODEX_RUNTIME_TARGET,
                f"{path}: Codex runtime root must use the isolated mount",
            )
        else:
            require(
                "REMOTE_DEV_CODEX_RUNTIME_ROOT" not in environment,
                f"{path}: Codex runtime state leaked into Antigravity environment",
            )
        if truenas:
            require("WEB_PASSWORD_FILE" not in environment, f"{path}: {role} file password remains")
            require(
                environment.get("WEB_PASSWORD") == "",
                f"{path}: {role} public YAML password must remain empty",
            )
        else:
            require(environment.get("WEB_PASSWORD_FILE") == "/run/secrets/web_password", f"{path}: {role} file target")
            require("WEB_PASSWORD" not in environment, f"{path}: {role} environment password leaked")

    require(
        all_sources["codex"].isdisjoint(all_sources["antigravity"]),
        f"{path}: agent services share persistent sources",
    )
    require(
        CODEX_RUNTIME_TARGET not in volume_map(services["antigravity"]),
        f"{path}: Antigravity can see Codex runtime state",
    )

    if truenas:
        require("secrets" not in config, f"{path}: TrueNAS home mode retained top-level secrets")
    else:
        secrets = config.get("secrets")
        require(isinstance(secrets, dict), f"{path}: top-level secrets missing")
        require(
            set(secrets) == {"web_password"},
            f"{path}: optional Antigravity secret leaked into the default model",
        )
        definition = secrets.get("web_password")
        require(isinstance(definition, dict), f"{path}: secret web_password missing")
        secret_file = definition.get("file")
        require(isinstance(secret_file, str), f"{path}: secret web_password file missing")
        require(
            secret_file.endswith("/data/secrets/codex/web_password.txt"),
            f"{path}: secret web_password outside canonical root",
        )

    for role in ("codex", "antigravity"):
        for mount in volume_map(services[role]).values():
            source = str(mount.get("source", ""))
            require(source not in {"/", "/root", "/home", "/mnt"}, f"{path}: broad mount {source}")
            require("docker.sock" not in source.lower(), f"{path}: Docker socket mount {source}")
            require("podman.sock" not in source.lower(), f"{path}: Podman socket mount {source}")


def tracked_repository_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False
    )
    if completed.returncode != 0:
        raise AssertionError("git ls-files failed: " + completed.stderr.decode(errors="replace"))
    return [ROOT / os.fsdecode(path) for path in completed.stdout.split(b"\0") if path]


def validate_repository_has_no_legacy_data_root() -> None:
    legacy_variable = "CODEX" + "_DATA_ROOT"
    legacy_path = "/mnt/Pool1/" + "codex"
    ignored_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz"}
    for path in tracked_repository_files():
        if not path.is_file() or path.suffix.lower() in ignored_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        require(legacy_variable not in text, f"legacy data-root variable remains in {path}")
        require(legacy_path not in text, f"legacy TrueNAS data path remains in {path}")


def validate_sources() -> None:
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    generic_text = GENERIC_COMPOSE.read_text(encoding="utf-8")
    truenas_text = TRUENAS_COMPOSE.read_text(encoding="utf-8")
    preflight_text = PREFLIGHT.read_text(encoding="utf-8")

    require("REMOTE_DEV_DATA_ROOT=../data" in env_text, ".env.example must define the data root")
    require("REMOTE_DEV_ENABLE_ANTIGRAVITY_SERVICE=0" in env_text, "Antigravity opt-in missing")
    require("profiles: [\"antigravity\"]" in generic_text, "generic Antigravity profile missing")
    require(generic_text.count("create_host_path: false") == 14, "generic bind protection count")
    require(truenas_text.count("create_host_path: false") == 13, "TrueNAS bind protection count")
    require("--include-antigravity" in preflight_text, "optional Antigravity preflight flag missing")
    require("--password-source" in preflight_text, "password source preflight option missing")
    require("\n      WEB_PASSWORD_FILE:" not in truenas_text, "TrueNAS home mode still uses password files")
    require("target: /run/secrets/web_password" not in truenas_text, "TrueNAS home mode still mounts passwords")
    require(truenas_text.count("WEB_PASSWORD: ''") == 2, "TrueNAS password placeholders must fail closed")
    for marker in (
        "workspaces/codex",
        "state/codex/agent",
        "state/codex/runtime",
        "secrets/codex/web_password.txt",
        "workspaces/antigravity",
        "state/antigravity/bin",
        "state/antigravity/runtime",
        "state/antigravity/vendor",
        "state/antigravity/gh",
        "state/antigravity/git",
        "state/antigravity/ssh",
        "secrets/antigravity/web_password.txt",
    ):
        require(marker in preflight_text, f"host preflight does not cover {marker}")


def main() -> int:
    validate_sources()
    validate_compose(GENERIC_COMPOSE, truenas=False)
    validate_compose(TRUENAS_COMPOSE, truenas=True)
    validate_repository_has_no_legacy_data_root()
    print("Canonical Remote Dev data-root and isolated mount boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
