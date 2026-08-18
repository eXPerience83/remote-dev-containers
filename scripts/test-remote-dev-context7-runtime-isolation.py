#!/usr/bin/env python3
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import tempfile


HELPER_OVERRIDE = os.environ.get("REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER")
HELPER = Path(
    HELPER_OVERRIDE
    or Path(__file__).resolve().parents[1] / "scripts" / "remote-dev-context7-device-login.py"
)


def load_helper():
    module_name = "remote_dev_context7_device_login_runtime"
    loader = importlib.machinery.SourceFileLoader(module_name, str(HELPER))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise AssertionError(f"could not load {HELPER}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def assert_distinct_private_npm_configs(module) -> None:
    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-npm-config-test-") as temp:
        root = Path(temp)
        environment = module.transient_environment(root, node_version="24.19.0")
        user_config = Path(environment["npm_config_userconfig"])
        global_config = Path(environment["npm_config_globalconfig"])
        if user_config == global_config:
            raise AssertionError("npm user/global config paths must be distinct")
        if user_config == Path("/dev/null") or global_config == Path("/dev/null"):
            raise AssertionError("npm config isolation must not double-load /dev/null")
        if user_config.parent != root or global_config.parent != root:
            raise AssertionError("npm config paths escaped the transient Context7 root")


def assert_restrictive_vendor_process_contract(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    captured: dict[str, object] = {}

    class SuccessProcess:
        pid = 515151

        def poll(self):
            return 0

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["kwargs"] = dict(kwargs)
        return SuccessProcess()

    def fake_killpg(pgid: int, sent_signal: int) -> None:
        if (pgid, sent_signal) != (SuccessProcess.pid, signal.SIGKILL):
            raise AssertionError("unexpected process-group signal during runtime regression")

    try:
        module.subprocess.Popen = fake_popen
        module.os.killpg = fake_killpg
        with open(os.devnull, encoding="utf-8") as cancel_stream:
            module.run_login_process(
                ["synthetic-ctx7"],
                cwd=Path("/tmp"),
                environment={"PATH": "/usr/bin:/bin"},
                cancel_stream=cancel_stream,
            )
    finally:
        module.subprocess.Popen = original_popen
        module.os.killpg = original_killpg

    kwargs = captured["kwargs"]
    if kwargs.get("umask") != 0o077:
        raise AssertionError(f"transient vendor process did not receive umask 077: {kwargs!r}")
    if kwargs.get("stdin") != subprocess.DEVNULL:
        raise AssertionError("transient vendor process still owns terminal stdin")
    if kwargs.get("start_new_session") is not True:
        raise AssertionError("transient vendor process is not isolated in its own process group")


def assert_bundled_npm_accepts_isolated_configs(module) -> None:
    if not module.NPM.exists() or not module.MISE_CONFIG.exists():
        if HELPER_OVERRIDE:
            raise AssertionError(
                "in-image Context7 npm/setpriv regression could not run: "
                f"npm={module.NPM} mise_config={module.MISE_CONFIG}"
            )
        print("Context7 bundled npm regression skipped: not running inside the image")
        return

    module.validate_executable(module.NPM, label="npm")
    node_version = module.configured_node_version()
    uid, gid = module.sandbox_identity()
    root = module.create_login_root(uid, gid)
    try:
        environment = module.transient_environment(root, node_version=node_version)
        command = [str(module.NPM), "--version"]
        if os.geteuid() == 0:
            module.validate_executable(module.SETPRIV, label="setpriv")
            command = [
                str(module.SETPRIV),
                "--reuid",
                str(uid),
                "--regid",
                str(gid),
                "--clear-groups",
                "--no-new-privs",
                *command,
            ]
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(
                "bundled npm rejected the isolated user/global config paths: "
                + result.stderr.strip()
            )
    finally:
        module.remove_login_root(root)


def main() -> int:
    module = load_helper()
    assert_distinct_private_npm_configs(module)
    assert_restrictive_vendor_process_contract(module)
    assert_bundled_npm_accepts_isolated_configs(module)
    print("Context7 npm/runtime isolation regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
