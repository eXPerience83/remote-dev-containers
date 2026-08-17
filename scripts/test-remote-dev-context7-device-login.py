#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "remote-dev-context7-device-login.py"
SYNTHETIC_KEY = "ctx7sk-test-device-key-do-not-use"


def load_helper():
    spec = importlib.util.spec_from_file_location("remote_dev_context7_device_login", HELPER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_credentials(path: Path, payload: dict[str, object], *, uid: int, gid: int) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)
    if os.geteuid() == 0:
        os.chown(path.parent, uid, gid)
        os.chown(path, uid, gid)


def assert_acquire_uses_isolated_environment(module) -> None:
    original_login_process = module.run_login_process
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_setpriv = module.SETPRIV
    captured: dict[str, object] = {}

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-device-test-") as temp:
        run_root = Path(temp) / "run"
        run_root.mkdir(mode=0o755)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.SETPRIV = Path("/bin/true")

        def fake_login_process(command, *, cwd, environment):
            uid, gid = module.sandbox_identity()
            captured["command"] = list(command)
            captured["environment"] = dict(environment)
            captured["cwd"] = Path(cwd)
            credentials = (
                Path(environment["XDG_CONFIG_HOME"])
                / module.CONTEXT7_CREDENTIALS_RELATIVE
            )
            write_credentials(
                credentials,
                {"access_token": SYNTHETIC_KEY, "token_type": "bearer"},
                uid=uid,
                gid=gid,
            )

        sensitive = {
            "OPENAI_API_KEY": "openai-test-secret",
            "GH_TOKEN": "github-test-secret",
            "CONTEXT7_API_KEY": "context7-old-test-secret",
            "CODEX_HOME": "/private/codex-home",
        }
        previous = {name: os.environ.get(name) for name in sensitive}
        os.environ.update(sensitive)
        try:
            module.run_login_process = fake_login_process
            value = module.acquire_api_key()
        finally:
            module.run_login_process = original_login_process
            module.RUN_ROOT = original_run_root
            module.NPM = original_npm
            module.SETPRIV = original_setpriv
            for name, value_before in previous.items():
                if value_before is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value_before

        if value != SYNTHETIC_KEY:
            raise AssertionError("device login did not return the synthetic Context7 API key")

        command = captured["command"]
        environment = captured["environment"]
        if f"--package={module.CONTEXT7_CLI_PACKAGE}" not in command:
            raise AssertionError("device login did not pin the exact Context7 CLI package")
        if "--ignore-scripts" not in command:
            raise AssertionError("transient npm execution did not disable lifecycle scripts")
        if f"--registry={module.NPM_REGISTRY}" not in command:
            raise AssertionError("transient npm execution did not pin the public npm registry")
        if command[-3:] != ["ctx7", "login", "--no-browser"]:
            raise AssertionError(f"unexpected Context7 CLI command tail: {command[-3:]!r}")
        for name, secret in sensitive.items():
            if name in environment or secret in "\n".join(command):
                raise AssertionError(f"sensitive caller state leaked into transient login: {name}")
        if environment.get("CTX7_TELEMETRY_DISABLED") != "1":
            raise AssertionError("Context7 telemetry was not disabled for transient login")
        if environment.get("npm_config_userconfig") != "/dev/null":
            raise AssertionError("transient npm execution can still consume user npm configuration")
        if environment.get("npm_config_globalconfig") != "/dev/null":
            raise AssertionError("transient npm execution can still consume global npm configuration")
        if environment.get("HOME") == os.environ.get("HOME"):
            raise AssertionError("transient Context7 login reused the caller HOME")

        cwd = captured["cwd"]
        if cwd.exists():
            raise AssertionError("transient Context7 login directory was not removed")


def assert_timeout_terminates_process_group(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    captured: dict[str, object] = {}
    signals: list[tuple[int, int]] = []

    class TimeoutProcess:
        pid = 424242

        def __init__(self) -> None:
            self.wait_calls = 0

        def wait(self, *, timeout):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired(["synthetic-ctx7"], timeout)
            return -signal.SIGTERM

    process = TimeoutProcess()

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return process

    def fake_killpg(pgid: int, sent_signal: int) -> None:
        signals.append((pgid, sent_signal))

    try:
        module.subprocess.Popen = fake_popen
        module.os.killpg = fake_killpg
        try:
            module.run_login_process(
                ["synthetic-ctx7"],
                cwd=Path("/tmp"),
                environment={"PATH": "/usr/bin:/bin"},
            )
        except module.DeviceLoginError as exc:
            if "timed out" not in str(exc):
                raise AssertionError(f"unexpected timeout error: {exc}") from exc
        else:
            raise AssertionError("timed-out Context7 device login unexpectedly succeeded")
    finally:
        module.subprocess.Popen = original_popen
        module.os.killpg = original_killpg

    kwargs = captured["kwargs"]
    if kwargs.get("start_new_session") is not True:
        raise AssertionError("transient Context7 CLI was not isolated into its own process group")
    expected_signals = [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    if signals != expected_signals:
        raise AssertionError(f"timed-out Context7 process group was not fully terminated: {signals!r}")


def assert_cleanup_failure_is_fatal(module) -> None:
    original_login_process = module.run_login_process
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_setpriv = module.SETPRIV
    original_rmtree = module.shutil.rmtree

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-cleanup-test-") as temp:
        run_root = Path(temp) / "run"
        run_root.mkdir(mode=0o755)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.SETPRIV = Path("/bin/true")

        def fake_login_process(command, *, cwd, environment):
            del command, cwd
            uid, gid = module.sandbox_identity()
            credentials = (
                Path(environment["XDG_CONFIG_HOME"])
                / module.CONTEXT7_CREDENTIALS_RELATIVE
            )
            write_credentials(
                credentials,
                {"access_token": SYNTHETIC_KEY, "token_type": "bearer"},
                uid=uid,
                gid=gid,
            )

        def fail_rmtree(path):
            del path
            raise OSError(13, "synthetic cleanup failure")

        try:
            module.run_login_process = fake_login_process
            module.shutil.rmtree = fail_rmtree
            try:
                module.acquire_api_key()
            except module.DeviceLoginError as exc:
                if "could not remove transient Context7 CLI/login state" not in str(exc):
                    raise AssertionError(f"unexpected cleanup error: {exc}") from exc
            else:
                raise AssertionError("Context7 login accepted a failed transient-state cleanup")
        finally:
            module.run_login_process = original_login_process
            module.RUN_ROOT = original_run_root
            module.NPM = original_npm
            module.SETPRIV = original_setpriv
            module.shutil.rmtree = original_rmtree


def assert_credentials_contract(module) -> None:
    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-credentials-test-") as temp:
        root = Path(temp)
        path = root / "credentials.json"
        uid = os.geteuid()
        gid = os.getegid()

        valid = {"access_token": SYNTHETIC_KEY, "token_type": "bearer"}
        write_credentials(path, valid, uid=uid, gid=gid)
        if module.read_credentials(path, expected_uid=uid) != SYNTHETIC_KEY:
            raise AssertionError("valid long-lived Context7 API-key state was rejected")

        invalid_payloads = (
            {"access_token": "not-a-context7-key", "token_type": "bearer"},
            {"access_token": SYNTHETIC_KEY, "token_type": "oauth"},
            {
                "access_token": SYNTHETIC_KEY,
                "token_type": "bearer",
                "refresh_token": "synthetic-refresh-token",
            },
            {"access_token": SYNTHETIC_KEY, "token_type": "bearer", "expires_in": 60},
        )
        for payload in invalid_payloads:
            write_credentials(path, payload, uid=uid, gid=gid)
            try:
                module.read_credentials(path, expected_uid=uid)
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError(f"unsafe Context7 credential shape was accepted: {payload!r}")

        write_credentials(path, valid, uid=uid, gid=gid)
        os.chmod(path, 0o644)
        try:
            module.read_credentials(path, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("group/world-readable Context7 credentials were accepted")


def assert_adoption_order_and_failure(module) -> None:
    original_run_manager = module.run_manager
    original_acquire = module.acquire_api_key
    calls: list[tuple[list[str], str | None]] = []

    def fake_manager(arguments: list[str], *, input_text: str | None = None) -> None:
        calls.append((list(arguments), input_text))

    try:
        module.run_manager = fake_manager
        module.acquire_api_key = lambda: SYNTHETIC_KEY
        if module.command_login(yes=True) != 0:
            raise AssertionError("synthetic device login command unexpectedly failed")
    finally:
        module.run_manager = original_run_manager
        module.acquire_api_key = original_acquire

    expected = [
        (["repair", "--yes"], None),
        (["repair", "--yes", "--api-key-stdin"], SYNTHETIC_KEY + "\n"),
    ]
    if calls != expected:
        raise AssertionError(f"unexpected device-login adoption sequence: {calls!r}")

    calls.clear()

    def fail_acquire() -> str:
        raise module.DeviceLoginError("synthetic login failure")

    try:
        module.run_manager = fake_manager
        module.acquire_api_key = fail_acquire
        try:
            module.command_login(yes=True)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("synthetic device-login failure unexpectedly succeeded")
    finally:
        module.run_manager = original_run_manager
        module.acquire_api_key = original_acquire

    if calls != [(["repair", "--yes"], None)]:
        raise AssertionError("failed device login attempted to replace the existing managed key")


def assert_role_gate(module) -> None:
    previous = os.environ.get("REMOTE_DEV_ROLE")
    try:
        os.environ["REMOTE_DEV_ROLE"] = "launcher"
        try:
            module.validate_role()
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("Context7 device login accepted a non-Codex role")
    finally:
        if previous is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = previous


def main() -> int:
    module = load_helper()
    if module.CONTEXT7_CLI_PACKAGE != "ctx7@0.5.7":
        raise AssertionError("Context7 device-login package pin drifted unexpectedly")
    assert_acquire_uses_isolated_environment(module)
    assert_timeout_terminates_process_group(module)
    assert_cleanup_failure_is_fatal(module)
    assert_credentials_contract(module)
    assert_adoption_order_and_failure(module)
    assert_role_gate(module)
    print("Context7 device-login isolation regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
