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

EXPECTED_TARGET_SUFFIXES = {
    "/workspace": "/workspaces/codex",
    "/root/.codex": "/state/codex/agent",
    "/root/.config/gh": "/state/codex/gh",
    "/root/.config/git": "/state/codex/git",
    "/root/.ssh": "/state/codex/ssh",
}
TRUENAS_ROOT = "/mnt/Pool1/remote-dev"


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion when a contract condition is not met."""
    if not condition:
        raise AssertionError(message)


def compose_environment() -> dict[str, str]:
    """Return the minimal host environment required to invoke Docker Compose."""
    return {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "XDG_RUNTIME_DIR")
        if key in os.environ
    }


def compose_config(path: Path) -> dict[str, object]:
    """Render one Compose file with deterministic empty user configuration."""
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
            capture_output=True,
            check=False,
        )
    if completed.returncode != 0:
        raise AssertionError(f"docker compose config failed for {path}:\n{completed.stderr}")
    return json.loads(completed.stdout)


def volume_map(service: dict[str, object]) -> dict[str, dict[str, object]]:
    """Index rendered long-syntax volume entries by their container target."""
    result: dict[str, dict[str, object]] = {}
    for mount in service.get("volumes", []):
        require(isinstance(mount, dict), "rendered volume must use long syntax")
        target = mount.get("target")
        require(isinstance(target, str), "rendered volume is missing a target")
        require(target not in result, f"duplicate mount target: {target}")
        result[target] = mount
    return result


def validate_bind_mount(path: Path, mount: dict[str, object], suffix: str) -> None:
    """Validate one narrow bind mount and its expected canonical source suffix."""
    source = mount.get("source")
    require(isinstance(source, str), f"{path}: bind mount source is missing")
    require(source.endswith(suffix), f"{path}: unexpected source {source} for {suffix}")
    require(mount.get("type") == "bind", f"{path}: {source} is not a bind mount")
    bind = mount.get("bind")
    require(isinstance(bind, dict), f"{path}: {source} has no bind options")
    # Compose may omit an explicitly false value from rendered JSON and some
    # releases may not enforce it at runtime. Source YAML and the authoritative
    # host preflight are checked separately below.
    require(
        bind.get("create_host_path") is not True,
        f"{path}: {source} explicitly enables automatic host-path creation",
    )


def validate_compose(path: Path, *, truenas: bool) -> None:
    """Validate service topology, exact mounts and secret boundaries for one stack."""
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


def tracked_repository_files() -> list[Path]:
    """Return only Git-tracked repository files, excluding ignored workspaces."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            "git ls-files failed while enumerating repository-owned inputs:\n"
            + completed.stderr.decode(errors="replace")
        )
    return [
        ROOT / os.fsdecode(relative_path)
        for relative_path in completed.stdout.split(b"\0")
        if relative_path
    ]


def validate_repository_has_no_legacy_data_root() -> None:
    """Reject legacy data-root names and paths in version-controlled sources."""
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
    """Check one canonical root, source-level bind defenses and host preflight."""
    env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
    generic_text = GENERIC_COMPOSE.read_text(encoding="utf-8")
    truenas_text = TRUENAS_COMPOSE.read_text(encoding="utf-8")
    preflight_text = PREFLIGHT.read_text(encoding="utf-8")

    require(
        "REMOTE_DEV_DATA_ROOT=../data" in env_text,
        ".env.example must define the canonical data root",
    )
    require("WEB_PASSWORD_PATH" not in env_text, ".env.example defines a second data-path variable")
    require("WEB_PASSWORD_PATH" not in generic_text, "generic Compose defines a second data-path variable")
    require(
        generic_text.count("${REMOTE_DEV_DATA_ROOT:-../data}") == 6,
        "all generic persistent paths must derive from REMOTE_DEV_DATA_ROOT",
    )
    require(
        "file: ${REMOTE_DEV_DATA_ROOT:-../data}/secrets/codex/web_password.txt"
        in generic_text,
        "generic password secret must derive from REMOTE_DEV_DATA_ROOT",
    )
    require(
        generic_text.count("create_host_path: false") == 5,
        "generic Compose must request no host-path creation on every persistent bind",
    )
    require(
        truenas_text.count("create_host_path: false") == 6,
        "TrueNAS Compose must request no host-path creation on every persistent bind",
    )
    for marker in (
        "workspaces/codex",
        "state/codex/agent",
        "state/codex/gh",
        "state/codex/git",
        "state/codex/ssh",
        "secrets/codex/web_password.txt",
    ):
        require(marker in preflight_text, f"host preflight does not cover {marker}")


def main() -> int:
    """Run all canonical data-layout validations."""
    validate_sources()
    validate_compose(GENERIC_COMPOSE, truenas=False)
    validate_compose(TRUENAS_COMPOSE, truenas=True)
    validate_repository_has_no_legacy_data_root()
    print("Canonical Remote Dev data-root and mount boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
