#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile


HELPER = Path(
    os.environ.get(
        "REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER",
        Path(__file__).resolve().parents[1] / "scripts" / "remote-dev-context7-device-login.py",
    )
)
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
    for directory in (path.parent.parent, path.parent):
        os.chmod(directory, 0o700)
        if os.geteuid() == 0:
            os.chown(directory, uid, gid)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)
    if os.geteuid() == 0:
        os.chown(path, uid, gid)


def write_mise_config(path: Path, node_version: str = "24.19.0") -> None:
    path.write_text(f'[tools]\nnode = "{node_version}"\n', encoding="utf-8")


def assert_acquire_uses_isolated_environment(module) -> None:
    original_login_process = module.run_login_process
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_mise_config = module.MISE_CONFIG
    original_setpriv = module.SETPRIV
    captured: dict[str, object] = {}

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-device-test-") as temp:
        temp_root = Path(temp)
        run_root = temp_root / "run"
        run_root.mkdir(mode=0o755)
        mise_config = temp_root / "mise.toml"
        write_mise_config(mise_config)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.MISE_CONFIG = mise_config
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
            module.MISE_CONFIG = original_mise_config
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
        if environment.get("MISE_NODE_VERSION") != "24.19.0":
            raise AssertionError("transient npm shim did not receive the bundled Node version explicitly")
        if environment.get("MISE_OFFLINE") != "1":
            raise AssertionError("mise shim resolution was not forced offline")
        if "MISE_CONFIG_DIR" in environment or "MISE_GLOBAL_CONFIG_FILE" in environment:
            raise AssertionError("unprivileged transient login still depends on root-owned mise config")

        cwd = captured["cwd"]
        if environment.get("TMPDIR") != str(cwd):
            raise AssertionError("transient Context7 login can use temporary files outside its private root")
        if environment.get("XDG_RUNTIME_DIR") != str(cwd):
            raise AssertionError("transient Context7 login can use XDG runtime state outside its private root")
        if environment.get("MISE_CACHE_DIR") != str(cwd / "mise-cache"):
            raise AssertionError("mise cache escaped the transient Context7 login root")
        if environment.get("MISE_TMP_DIR") != str(cwd):
            raise AssertionError("mise temporary state escaped the transient Context7 login root")
        if cwd.exists():
            raise AssertionError("transient Context7 login directory was not removed")


def assert_node_version_contract(module) -> None:
    original_mise_config = module.MISE_CONFIG
    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-mise-test-") as temp:
        mise_config = Path(temp) / "mise.toml"
        module.MISE_CONFIG = mise_config
        try:
            write_mise_config(mise_config, "24.19.0")
            if module.configured_node_version() != "24.19.0":
                raise AssertionError("valid bundled Node version was not resolved")

            for invalid in ("latest", "24", "24.19.x", ""):
                write_mise_config(mise_config, invalid)
                try:
                    module.configured_node_version()
                except module.DeviceLoginError:
                    pass
                else:
                    raise AssertionError(f"invalid bundled Node version was accepted: {invalid!r}")
        finally:
            module.MISE_CONFIG = original_mise_config


def assert_manager_preflight_is_read_only(module) -> None:
    original_run = module.subprocess.run
    original_python = module.PYTHON
    captured: list[list[str]] = []

    def response(state: str, returncode: int = 0):
        def fake_run(command, **kwargs):
            captured.append(list(command))
            if "input" in kwargs:
                raise AssertionError("read-only Context7 preflight unexpectedly supplied stdin")
            return subprocess.CompletedProcess(command, returncode, stdout=state + "\n", stderr="")

        return fake_run

    try:
        module.PYTHON = Path("/bin/true")
        for state in module.PREFLIGHT_ALLOWED_STATES:
            module.subprocess.run = response(state)
            module.preflight_manager_state()

        rejected = (
            (module.PREFLIGHT_UNMANAGED_STATE, 0),
            ("Context7: configured but API-key state is unsafe", 3),
            ("unexpected synthetic state", 0),
        )
        for state, returncode in rejected:
            module.subprocess.run = response(state, returncode)
            try:
                module.preflight_manager_state()
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError(f"unsafe/unexpected Context7 preflight state was accepted: {state!r}")
    finally:
        module.subprocess.run = original_run
        module.PYTHON = original_python

    if not captured:
        raise AssertionError("Context7 preflight did not invoke the manager")
    for command in captured:
        if command[-2:] != ["status", "--menu"]:
            raise AssertionError(f"Context7 preflight was not read-only: {command!r}")


def assert_success_reaps_process_group(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    captured: dict[str, object] = {}
    signals: list[tuple[int, int]] = []

    class SuccessProcess:
        pid = 313131

        def wait(self, *, timeout):
            del timeout
            return 0

    process = SuccessProcess()

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return process

    def fake_killpg(pgid: int, sent_signal: int) -> None:
        signals.append((pgid, sent_signal))

    try:
        module.subprocess.Popen = fake_popen
        module.os.killpg = fake_killpg
        module.run_login_process(
            ["synthetic-ctx7"],
            cwd=Path("/tmp"),
            environment={"PATH": "/usr/bin:/bin"},
        )
    finally:
        module.subprocess.Popen = original_popen
        module.os.killpg = original_killpg

    kwargs = captured["kwargs"]
    if kwargs.get("start_new_session") is not True:
        raise AssertionError("successful transient Context7 CLI was not isolated into its own process group")
    if signals != [(process.pid, signal.SIGKILL)]:
        raise AssertionError(f"successful Context7 login left a residual process group: {signals!r}")


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
    original_mise_config = module.MISE_CONFIG
    original_setpriv = module.SETPRIV
    original_rmtree = module.shutil.rmtree

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-cleanup-test-") as temp:
        temp_root = Path(temp)
        run_root = temp_root / "run"
        run_root.mkdir(mode=0o755)
        mise_config = temp_root / "mise.toml"
        write_mise_config(mise_config)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.MISE_CONFIG = mise_config
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
            module.MISE_CONFIG = original_mise_config
            module.SETPRIV = original_setpriv
            module.shutil.rmtree = original_rmtree


def assert_credentials_contract(module) -> None:
    original_run_root = module.RUN_ROOT
    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-credentials-test-") as temp:
        root = Path(temp) / "remote-dev-context7-login-test"
        root.mkdir(mode=0o700)
        run_root = root.parent
        module.RUN_ROOT = run_root
        uid = os.geteuid()
        gid = os.getegid()
        path = root / "config" / module.CONTEXT7_CREDENTIALS_RELATIVE

        valid = {"access_token": SYNTHETIC_KEY, "token_type": "bearer"}
        write_credentials(path, valid, uid=uid, gid=gid)
        if module.read_credentials(root, expected_uid=uid) != SYNTHETIC_KEY:
            raise AssertionError("valid long-lived Context7 API-key state was rejected")

        invalid_payloads = (
            {"access_token": "not-a-context7-key", "token_type": "bearer"},
            {"access_token": "ctx7sk-", "token_type": "bearer"},
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
                module.read_credentials(root, expected_uid=uid)
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError(f"unsafe Context7 credential shape was accepted: {payload!r}")

        write_credentials(path, valid, uid=uid, gid=gid)
        os.chmod(path, 0o644)
        try:
            module.read_credentials(root, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("group/world-readable Context7 credentials were accepted")

        shutil.rmtree(root / "config")
        external = run_root / "external-config"
        external_path = external / module.CONTEXT7_CREDENTIALS_RELATIVE
        write_credentials(external_path, valid, uid=uid, gid=gid)
        (root / "config").symlink_to(external, target_is_directory=True)
        try:
            module.read_credentials(root, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("Context7 credential reader followed a vendor-controlled parent symlink")

    module.RUN_ROOT = original_run_root


def assert_adoption_order_and_failure(module) -> None:
    original_run_manager = module.run_manager
    original_preflight = module.preflight_manager_state
    original_acquire = module.acquire_api_key
    calls: list[tuple[list[str], str | None]] = []
    preflight_calls = 0

    def fake_manager(arguments: list[str], *, input_text: str | None = None) -> None:
        calls.append((list(arguments), input_text))

    def fake_preflight() -> None:
        nonlocal preflight_calls
        preflight_calls += 1

    try:
        module.run_manager = fake_manager
        module.preflight_manager_state = fake_preflight
        module.acquire_api_key = lambda: SYNTHETIC_KEY
        if module.command_login(yes=True) != 0:
            raise AssertionError("synthetic device login command unexpectedly failed")
    finally:
        module.run_manager = original_run_manager
        module.preflight_manager_state = original_preflight
        module.acquire_api_key = original_acquire

    expected = [
        (["repair", "--yes", "--api-key-stdin"], SYNTHETIC_KEY + "\n"),
    ]
    if calls != expected or preflight_calls != 1:
        raise AssertionError(
            f"unexpected device-login adoption sequence: preflight={preflight_calls}, calls={calls!r}"
        )

    calls.clear()
    preflight_calls = 0

    def fail_acquire() -> str:
        raise module.DeviceLoginError("synthetic login failure")

    try:
        module.run_manager = fake_manager
        module.preflight_manager_state = fake_preflight
        module.acquire_api_key = fail_acquire
        try:
            module.command_login(yes=True)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("synthetic device-login failure unexpectedly succeeded")
    finally:
        module.run_manager = original_run_manager
        module.preflight_manager_state = original_preflight
        module.acquire_api_key = original_acquire

    if calls or preflight_calls != 1:
        raise AssertionError(
            "failed device login mutated managed Context7 state instead of preserving the existing key/config"
        )


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
    assert_node_version_contract(module)
    assert_manager_preflight_is_read_only(module)
    assert_acquire_uses_isolated_environment(module)
    assert_success_reaps_process_group(module)
    assert_timeout_terminates_process_group(module)
    assert_cleanup_failure_is_fatal(module)
    assert_credentials_contract(module)
    assert_adoption_order_and_failure(module)
    assert_role_gate(module)
    print("Context7 device-login isolation regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
