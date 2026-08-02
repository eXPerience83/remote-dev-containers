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

EXPECTED_TARGET_SUFFIXES = {
    "/workspace": "/workspaces/codex",
    "/root/.codex": "/state/codex/agent",
    "/root/.config/gh": "/state/codex/gh",
    "/root/.config/git": "/state/codex/git",
    "/root/.ssh": "/state/codex/ssh",
}
TRUENAS_ROOT = "/mnt/Pool1/remote-dev"


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
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
        bind.get("create_host_path") is False,
        f"{path}: {source} may silently create a missing host path",
    )


def validate_compose(path: Path, *, truenas: bool) -> None:
    config = compose_config(path)
    services = config.get("services")
    require(isinstance(services, dict), f"{path}: services missing")
    require(set(services) == {"launcher", "codex"}, f"{path}: unexpected services")

    launcher = services["launcher"]
    codex = services["codex"]
    require(isinstance(launcher, dict), f"{path}: invalid launcher service")
    require(isinstance(codex, dict), f"{path}: invalid Codex service")
    require(volume_map(launcher) == {}, f"{path}: launcher must remain mount-free")

    codex_mounts = volume_map(codex)
    expected_targets = set(EXPECTED_TARGET_SUFFIXES)
    if truenas:
        expected_targets.add("/run/secrets/web_password")
    require(
        set(codex_mounts) == expected_targets,
        f"{path}: unexpected Codex mount targets: {sorted(codex_mounts)}",
    )

    for target, suffix in EXPECTED_TARGET_SUFFIXES.items():
        mount = codex_mounts[target]
        validate_bind_mount(path, mount, suffix)
        source = str(mount["source"])
        if truenas:
            require(
                source == f"{TRUENAS_ROOT}{suffix}",
                f"{path}: TrueNAS source must stay under {TRUENAS_ROOT}: {source}",
            )

    if truenas:
        password_mount = codex_mounts["/run/secrets/web_password"]
        validate_bind_mount(path, password_mount, "/secrets/codex/web_password.txt")
        require(
            password_mount.get("read_only") is True,
            f"{path}: password bind must be read-only",
        )
        require(
            password_mount.get("source")
            == f"{TRUENAS_ROOT}/secrets/codex/web_password.txt",
            f"{path}: unexpected TrueNAS password source",
        )
    else:
        secrets = config.get("secrets")
        require(isinstance(secrets, dict), f"{path}: top-level secrets missing")
        password = secrets.get("web_password")
        require(isinstance(password, dict), f"{path}: web_password secret missing")
        password_file = password.get("file")
        require(isinstance(password_file, str), f"{path}: password file missing")
        require(
            password_file.endswith("/data/secrets/codex/web_password.txt"),
            f"{path}: password file is outside the canonical data layout: {password_file}",
        )

    for mount in codex_mounts.values():
        source = str(mount.get("source", ""))
        require(source not in {"/", "/root", "/home", "/mnt"}, f"{path}: broad mount {source}")
        require("docker.sock" not in source.lower(), f"{path}: Docker socket mount {source}")
        require("podman.sock" not in source.lower(), f"{path}: Podman socket mount {source}")


def validate_repository_has_no_legacy_data_root() -> None:
    legacy_variable = "CODEX" + "_DATA_ROOT"
    legacy_path = "/mnt/Pool1/" + "codex"
    ignored_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz"}

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in ignored_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        require(legacy_variable not in text, f"legacy data-root variable remains in {path}")
        require(legacy_path not in text, f"legacy TrueNAS data path remains in {path}")


def validate_sources() -> None:
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    require(
        "REMOTE_DEV_DATA_ROOT=../data" in env_text,
        ".env.example must define the canonical data root",
    )
    generic_text = GENERIC_COMPOSE.read_text(encoding="utf-8")
    require(
        "${REMOTE_DEV_DATA_ROOT:-../data}" in generic_text,
        "generic Compose must derive role mounts from REMOTE_DEV_DATA_ROOT",
    )
    require(
        "create_host_path: false" in generic_text
        and "create_host_path: false" in TRUENAS_COMPOSE.read_text(encoding="utf-8"),
        "Compose examples must fail instead of creating missing host paths",
    )


def main() -> int:
    validate_sources()
    validate_compose(GENERIC_COMPOSE, truenas=False)
    validate_compose(TRUENAS_COMPOSE, truenas=True)
    validate_repository_has_no_legacy_data_root()
    print("Canonical Remote Dev data-root and mount boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
