#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEVICE_HELPER = REPO_ROOT / "scripts" / "remote-dev-context7-device-login.py"
MANAGER = REPO_ROOT / "scripts" / "remote-dev-context7.py"
SYNTHETIC_OLD_KEY = "ctx7sk-test-existing-key-do-not-use"
SYNTHETIC_NEW_KEY = "ctx7sk-test-device-key-do-not-use"


def load_device_helper():
    spec = importlib.util.spec_from_file_location("remote_dev_context7_device_adoption", DEVICE_HELPER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {DEVICE_HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manager_environment(codex_home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    environment["REMOTE_DEV_ROLE"] = "codex"
    return environment


def run_manager(codex_home: Path, arguments: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(
        [sys.executable, str(MANAGER), *arguments],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=manager_environment(codex_home),
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Context7 manager failed for {arguments!r}: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return result.stdout.strip()


def snapshot(codex_home: Path) -> tuple[bytes, bytes, int, int, str]:
    config = codex_home / "config.toml"
    state_dir = codex_home / ".remote-dev-context7"
    key_file = state_dir / "api-key"
    return (
        config.read_bytes(),
        key_file.read_bytes(),
        stat.S_IMODE(state_dir.stat().st_mode),
        stat.S_IMODE(key_file.stat().st_mode),
        run_manager(codex_home, ["status", "--menu"]),
    )


def assert_device_adoption_matches_manual_api_key_path(module) -> None:
    original_python = module.PYTHON
    original_manager = module.MANAGER
    original_acquire = module.acquire_api_key
    previous_home = os.environ.get("CODEX_HOME")
    previous_role = os.environ.get("REMOTE_DEV_ROLE")

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-adoption-test-") as temp:
        root = Path(temp)
        device_home = root / "device-home"
        manual_home = root / "manual-home"
        for home in (device_home, manual_home):
            home.mkdir(mode=0o700)
            (home / "config.toml").write_text(
                '[features]\nsynthetic_context7_regression = true\n',
                encoding="utf-8",
            )
            run_manager(
                home,
                ["install", "--yes", "--api-key-stdin"],
                input_text=SYNTHETIC_OLD_KEY + "\n",
            )

        try:
            module.PYTHON = Path(sys.executable)
            module.MANAGER = MANAGER
            module.acquire_api_key = lambda *, cli_channel: (
                SYNTHETIC_NEW_KEY,
                "0.5.8",
                True,
            )
            os.environ["CODEX_HOME"] = str(device_home)
            os.environ["REMOTE_DEV_ROLE"] = "codex"

            if module.command_login(yes=True, cli_channel="reviewed") != 0:
                raise AssertionError("synthetic device adoption unexpectedly failed")

            run_manager(
                manual_home,
                ["repair", "--yes", "--api-key-stdin"],
                input_text=SYNTHETIC_NEW_KEY + "\n",
            )

            device_snapshot = snapshot(device_home)
            manual_snapshot = snapshot(manual_home)
            if device_snapshot != manual_snapshot:
                raise AssertionError(
                    "device-login adoption diverged from the proven manual API-key manager path"
                )
            if device_snapshot[2:4] != (0o700, 0o600):
                raise AssertionError(
                    f"device-login adoption weakened managed-key permissions: {device_snapshot[2:4]!r}"
                )
            if SYNTHETIC_NEW_KEY.encode() in device_snapshot[0]:
                raise AssertionError("device-login API key leaked into managed Codex TOML")

            before_failure = snapshot(device_home)

            def fail_acquire(*, cli_channel):
                del cli_channel
                raise module.DeviceLoginError("synthetic device-login failure")

            module.acquire_api_key = fail_acquire
            try:
                module.command_login(yes=True, cli_channel="reviewed")
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError("synthetic failed device login unexpectedly succeeded")

            if snapshot(device_home) != before_failure:
                raise AssertionError(
                    "failed device login changed the previously working managed API-key state"
                )
        finally:
            module.PYTHON = original_python
            module.MANAGER = original_manager
            module.acquire_api_key = original_acquire
            if previous_home is None:
                os.environ.pop("CODEX_HOME", None)
            else:
                os.environ["CODEX_HOME"] = previous_home
            if previous_role is None:
                os.environ.pop("REMOTE_DEV_ROLE", None)
            else:
                os.environ["REMOTE_DEV_ROLE"] = previous_role


def main() -> int:
    module = load_device_helper()
    assert_device_adoption_matches_manual_api_key_path(module)
    print("Context7 device-login/manual-key convergence regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
