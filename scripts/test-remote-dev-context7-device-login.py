#!/usr/bin/env python3
from __future__ import annotations

import base64
import builtins
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time


HELPER = Path(
    os.environ.get(
        "REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER",
        Path(__file__).resolve().parents[1] / "scripts" / "remote-dev-context7-device-login.py",
    )
)
SYNTHETIC_KEY = "ctx7sk-test-device-key-do-not-use"
SYNTHETIC_PACKAGE = b"synthetic-context7-package-bytes"
SYNTHETIC_INTEGRITY = "sha512-" + base64.b64encode(
    hashlib.sha512(SYNTHETIC_PACKAGE).digest()
).decode("ascii")


class PackageResponse:
    def __init__(self, data: bytes, url: str):
        self.data = data
        self.url = url
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc_type, exc, traceback
        return False

    def geturl(self) -> str:
        return self.url

    def read(self, size: int) -> bytes:
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


def load_helper():
    spec = importlib.util.spec_from_file_location(
        "remote_dev_context7_device_login", HELPER
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {HELPER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def package_metadata(module, version: str = "0.5.8") -> dict[str, str]:
    return {
        "name": "ctx7",
        "version": version,
        "license": "MIT",
        "integrity": SYNTHETIC_INTEGRITY,
        "tarball": module.exact_tarball_url(version),
    }


def package_registry_payload(module, version: str = "0.5.8") -> dict[str, str]:
    metadata = package_metadata(module, version)
    return {
        "name": metadata["name"],
        "version": metadata["version"],
        "license": metadata["license"],
        "dist.integrity": metadata["integrity"],
        "dist.tarball": metadata["tarball"],
    }


def write_credentials(
    path: Path, payload: dict[str, object], *, uid: int, gid: int
) -> None:
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


def assert_reviewed_version_contract(module) -> None:
    if module.REVIEWED_CONTEXT7_CLI_VERSION != "0.5.8":
        raise AssertionError("Context7 reviewed CLI version drifted unexpectedly")
    if module.reviewed_cli_version() != "0.5.8":
        raise AssertionError("reviewed Context7 CLI version was not resolved")
    if module.reviewed_cli_integrity() != module.REVIEWED_CONTEXT7_CLI_INTEGRITY:
        raise AssertionError("reviewed Context7 CLI integrity was not resolved")
    for invalid in ("latest", "0.5", "0.5.x", ""):
        try:
            module.exact_version(invalid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError(
                f"mutable/invalid Context7 CLI version was accepted: {invalid!r}"
            )


def assert_repo_version_pin_sync(module) -> None:
    root = Path(__file__).resolve().parents[1]
    versions_file = root / "versions.env"
    if not versions_file.is_file():
        # Installed/in-image helper tests do not carry the source tree.
        return
    values: dict[str, str] = {}
    for line in versions_file.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        values[name] = value
    if (
        values.get("CONTEXT7_CLI_VERSION")
        != module.REVIEWED_CONTEXT7_CLI_VERSION
    ):
        raise AssertionError(
            "versions.env and the Context7 reviewed CLI runtime pin are inconsistent"
        )
    if (
        values.get("CONTEXT7_CLI_SRI_SHA512")
        != module.REVIEWED_CONTEXT7_CLI_INTEGRITY
    ):
        raise AssertionError(
            "versions.env and the Context7 reviewed CLI integrity are inconsistent"
        )


def assert_package_metadata_contract(module) -> None:
    original = module.npm_json
    try:
        module.npm_json = lambda *args, **kwargs: package_registry_payload(module)
        metadata = module.resolve_package_metadata(
            "0.5.8",
            uid=os.geteuid(),
            gid=os.getegid(),
            cwd=Path("/tmp"),
            environment={},
        )
        if metadata != package_metadata(module):
            raise AssertionError("valid Context7 npm package metadata was not accepted")

        module.npm_json = lambda *args, **kwargs: [package_registry_payload(module)]
        metadata = module.resolve_package_metadata(
            "0.5.8",
            uid=os.geteuid(),
            gid=os.getegid(),
            cwd=Path("/tmp"),
            environment={},
        )
        if metadata != package_metadata(module):
            raise AssertionError("npm 12 singleton-array metadata was not accepted")

        for payload in ([], [{}, {}], ["not-an-object"], "not-an-object"):
            module.npm_json = lambda *args, payload=payload, **kwargs: payload
            try:
                module.resolve_package_metadata(
                    "0.5.8",
                    uid=os.geteuid(),
                    gid=os.getegid(),
                    cwd=Path("/tmp"),
                    environment={},
                )
            except module.DeviceLoginError as exc:
                if "unexpected shape" not in str(exc):
                    raise AssertionError(
                        f"unexpected metadata-shape error: {exc}"
                    ) from exc
            else:
                raise AssertionError(
                    f"unsupported npm metadata shape was accepted: {payload!r}"
                )

        bad_payloads = (
            {
                **package_registry_payload(module),
                "name": "other",
            },
            {
                **package_registry_payload(module),
                "version": "latest",
            },
            {
                **package_registry_payload(module),
                "license": "GPL-3.0",
            },
            {
                **package_registry_payload(module),
                "dist.integrity": "",
            },
            {
                **package_registry_payload(module),
                "dist.integrity": "sha512-not-valid-base64***",
            },
            {
                **package_registry_payload(module),
                "dist.tarball": "https://evil.example/ctx7.tgz",
            },
        )
        for payload in bad_payloads:
            module.npm_json = lambda *args, payload=payload, **kwargs: payload
            try:
                module.resolve_package_metadata(
                    "0.5.8",
                    uid=os.geteuid(),
                    gid=os.getegid(),
                    cwd=Path("/tmp"),
                    environment={},
                )
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError(
                    f"unsafe Context7 npm metadata was accepted: {payload!r}"
                )
    finally:
        module.npm_json = original


def assert_metadata_timeout_is_bounded(module) -> None:
    original_run = module.subprocess.run
    captured: dict[str, object] = {}

    def timeout(command, **kwargs):
        captured["command"] = command
        captured["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    try:
        module.subprocess.run = timeout
        try:
            module.npm_json(
                ["view", "ctx7@0.5.8", "--json"],
                uid=os.geteuid(),
                gid=os.getegid(),
                cwd=Path("/tmp"),
                environment={},
            )
        except module.DeviceLoginError as exc:
            if "could not resolve" not in str(exc):
                raise AssertionError(
                    f"unexpected npm metadata timeout error: {exc}"
                ) from exc
        else:
            raise AssertionError("timed-out npm metadata lookup unexpectedly succeeded")
    finally:
        module.subprocess.run = original_run

    timeout_value = captured.get("timeout")
    if (
        not isinstance(timeout_value, float)
        or timeout_value <= 0
        or timeout_value > module.METADATA_TIMEOUT_SECONDS
    ):
        raise AssertionError(
            "npm metadata lookup does not have the configured total subprocess timeout"
        )


def assert_reviewed_latest_selection(module) -> None:
    original_reviewed = module.reviewed_cli_version
    original_integrity = module.reviewed_cli_integrity
    original_resolve = module.resolve_package_metadata
    original_input = builtins.input
    original_stdin = module.sys.stdin

    class Tty:
        def isatty(self):
            return True

    try:
        module.reviewed_cli_version = lambda: "0.5.8"
        module.reviewed_cli_integrity = lambda: SYNTHETIC_INTEGRITY
        module.sys.stdin = Tty()

        def resolve(specifier, **kwargs):
            del kwargs
            if specifier == "latest":
                return package_metadata(module, "0.5.9")
            return package_metadata(module, specifier)

        module.resolve_package_metadata = resolve

        try:
            module.validate_reviewed_metadata(
                {**package_metadata(module), "integrity": "sha512-" + "A" * 88}
            )
        except module.DeviceLoginError as exc:
            if "reviewed artifact" not in str(exc):
                raise AssertionError(
                    f"unexpected reviewed-integrity mismatch error: {exc}"
                ) from exc
        else:
            raise AssertionError("reviewed Context7 metadata accepted a changed SRI")

        builtins.input = lambda prompt="": "1"
        selected, reviewed = module.choose_cli_metadata(
            "auto", uid=1, gid=1, cwd=Path("/tmp"), environment={}
        )
        if selected["version"] != "0.5.8" or reviewed is not True:
            raise AssertionError("reviewed Context7 CLI selection failed")

        builtins.input = lambda prompt="": "2"
        selected, reviewed = module.choose_cli_metadata(
            "auto", uid=1, gid=1, cwd=Path("/tmp"), environment={}
        )
        if selected["version"] != "0.5.9" or reviewed is not False:
            raise AssertionError(
                "latest review-pending Context7 CLI selection failed"
            )

        selected, reviewed = module.choose_cli_metadata(
            "latest", uid=1, gid=1, cwd=Path("/tmp"), environment={}
        )
        if selected["version"] != "0.5.9" or reviewed is not False:
            raise AssertionError("explicit latest Context7 CLI selection failed")

        def reject_latest(specifier, **kwargs):
            del kwargs
            if specifier == "latest":
                raise module.DeviceLoginError("synthetic latest rejection")
            return package_metadata(module, specifier)

        module.resolve_package_metadata = reject_latest
        selected, reviewed = module.choose_cli_metadata(
            "auto", uid=1, gid=1, cwd=Path("/tmp"), environment={}
        )
        if selected["version"] != "0.5.8" or reviewed is not True:
            raise AssertionError(
                "rejected latest prevented use of the reviewed Context7 CLI"
            )
        try:
            module.choose_cli_metadata(
                "latest", uid=1, gid=1, cwd=Path("/tmp"), environment={}
            )
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError("explicit latest accepted rejected metadata")
    finally:
        module.reviewed_cli_version = original_reviewed
        module.reviewed_cli_integrity = original_integrity
        module.resolve_package_metadata = original_resolve
        builtins.input = original_input
        module.sys.stdin = original_stdin


def assert_acquire_uses_isolated_environment(module) -> None:
    original_login_process = module.run_login_process
    original_choose = module.choose_cli_metadata
    original_open_package = module.open_package_url
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_mise_config = module.MISE_CONFIG
    original_setpriv = module.SETPRIV
    captured: dict[str, object] = {}

    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-device-test-"
    ) as temp:
        temp_root = Path(temp)
        os.chmod(temp_root, 0o755)
        run_root = temp_root / "run"
        run_root.mkdir(mode=0o755)
        mise_config = temp_root / "mise.toml"
        write_mise_config(mise_config)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.MISE_CONFIG = mise_config
        module.SETPRIV = Path("/bin/true")
        module.choose_cli_metadata = lambda *args, **kwargs: (
            package_metadata(module),
            True,
        )
        module.open_package_url = lambda url, *, environment: PackageResponse(
            SYNTHETIC_PACKAGE, url
        )

        def fake_login_process(
            command, *, cwd, environment, cancel_stream=None
        ):
            del cancel_stream
            uid, gid = module.sandbox_identity()
            captured["command"] = list(command)
            captured["environment"] = dict(environment)
            captured["cwd"] = Path(cwd)
            package_argument = next(
                item for item in command if item.startswith("--package=")
            )
            package_path = Path(package_argument.removeprefix("--package="))
            package_info = package_path.stat()
            captured["package_path"] = package_path
            captured["package_mode"] = package_info.st_mode & 0o777
            captured["package_uid"] = package_info.st_uid
            captured["package_gid"] = package_info.st_gid

            replacement = Path(cwd) / "replacement.tgz"
            replacement.write_bytes(b"synthetic-unverified-replacement")
            os.chmod(replacement, 0o600)
            if os.geteuid() == 0:
                os.chown(replacement, uid, gid)
                prefix = [
                    str(original_setpriv),
                    "--reuid",
                    str(uid),
                    "--regid",
                    str(gid),
                    "--clear-groups",
                    "--no-new-privs",
                ]
                overwrite = subprocess.run(
                    [*prefix, "/bin/cp", str(replacement), str(package_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                rename = subprocess.run(
                    [*prefix, "/bin/mv", str(replacement), str(package_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                if overwrite.returncode == 0 or rename.returncode == 0:
                    raise AssertionError(
                        "the vendor UID could replace the verified Context7 tarball"
                    )
                if package_path.read_bytes() != SYNTHETIC_PACKAGE:
                    raise AssertionError(
                        "the verified Context7 tarball changed before vendor execution"
                    )
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
        development = {
            "TMPDIR": "/workspace/.remote-dev-tmp/tmp",
            "TMP": "/workspace/.remote-dev-tmp/tmp",
            "TEMP": "/workspace/.remote-dev-tmp/tmp",
            "UV_CACHE_DIR": "/workspace/.remote-dev-tmp/uv-cache",
            "NPM_CONFIG_CACHE": "/workspace/.remote-dev-tmp/npm-cache",
            "PIP_CACHE_DIR": "/workspace/.remote-dev-tmp/pip-cache",
        }
        previous = {
            name: os.environ.get(name) for name in (*sensitive, *development)
        }
        os.environ.update(sensitive)
        os.environ.update(development)
        try:
            module.run_login_process = fake_login_process
            value, version, reviewed = module.acquire_api_key(
                cli_channel="reviewed"
            )
        finally:
            module.run_login_process = original_login_process
            module.choose_cli_metadata = original_choose
            module.open_package_url = original_open_package
            module.RUN_ROOT = original_run_root
            module.NPM = original_npm
            module.MISE_CONFIG = original_mise_config
            module.SETPRIV = original_setpriv
            for name, value_before in previous.items():
                if value_before is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value_before

        if (value, version, reviewed) != (
            SYNTHETIC_KEY,
            "0.5.8",
            True,
        ):
            raise AssertionError(
                "device login did not return the synthetic reviewed Context7 result"
            )

        command = captured["command"]
        environment = captured["environment"]
        cwd = captured["cwd"]
        package_arguments = [
            item for item in command if item.startswith("--package=")
        ]
        if len(package_arguments) != 1:
            raise AssertionError(
                "device login did not execute the locally verified Context7 tarball: "
                f"{package_arguments!r}"
            )
        package_path = captured["package_path"]
        if package_path.parent == cwd or not package_path.parent.name.startswith(
            "remote-dev-context7-package-"
        ):
            raise AssertionError(
                "verified Context7 package was not separated from vendor-writable state"
            )
        expected_owner = 0 if os.geteuid() == 0 else os.geteuid()
        expected_group = module.SANDBOX_GID if os.geteuid() == 0 else os.getegid()
        if (
            captured["package_uid"] != expected_owner
            or captured["package_gid"] != expected_group
            or captured["package_mode"] != 0o440
        ):
            raise AssertionError(
                "verified Context7 package ownership/mode boundary is unsafe: "
                f"uid={captured['package_uid']} gid={captured['package_gid']} "
                f"mode={captured['package_mode']!r}"
            )
        if any("ctx7@" in item for item in command):
            raise AssertionError(
                "device login re-resolved Context7 from npm after integrity verification"
            )
        if "--ignore-scripts" not in command:
            raise AssertionError(
                "transient npm execution did not disable lifecycle scripts"
            )
        if f"--registry={module.NPM_REGISTRY}" not in command:
            raise AssertionError(
                "transient npm execution did not pin the public npm registry"
            )
        if command[-3:] != ["ctx7", "login", "--no-browser"]:
            raise AssertionError(
                f"unexpected Context7 CLI command tail: {command[-3:]!r}"
            )
        for name, secret in sensitive.items():
            if name in environment or secret in "\n".join(command):
                raise AssertionError(
                    f"sensitive caller state leaked into transient login: {name}"
                )
        if environment.get("TMPDIR") == development["TMPDIR"]:
            raise AssertionError("Context7 login inherited development TMPDIR")
        for name in ("TMP", "TEMP", "UV_CACHE_DIR", "NPM_CONFIG_CACHE", "PIP_CACHE_DIR"):
            if name in environment:
                raise AssertionError(
                    f"Context7 login inherited development environment: {name}"
                )
        if environment.get("CTX7_TELEMETRY_DISABLED") != "1":
            raise AssertionError(
                "Context7 telemetry was not disabled for transient login"
            )
        user_config = Path(environment["npm_config_userconfig"])
        global_config = Path(environment["npm_config_globalconfig"])
        if user_config == global_config:
            raise AssertionError(
                "transient npm user/global configuration paths are not distinct"
            )
        if user_config == Path("/dev/null") or global_config == Path(
            "/dev/null"
        ):
            raise AssertionError(
                "transient npm config isolation still relies on /dev/null"
            )
        if user_config.parent != cwd or global_config.parent != cwd:
            raise AssertionError(
                "transient npm config paths escaped the private login root"
            )
        if environment.get("HOME") == os.environ.get("HOME"):
            raise AssertionError("transient Context7 login reused the caller HOME")
        if environment.get("MISE_NODE_VERSION") != "24.19.0":
            raise AssertionError(
                "transient npm shim did not receive the bundled Node version explicitly"
            )
        if environment.get("MISE_OFFLINE") != "1":
            raise AssertionError("mise shim resolution was not forced offline")
        if (
            "MISE_CONFIG_DIR" in environment
            or "MISE_GLOBAL_CONFIG_FILE" in environment
        ):
            raise AssertionError(
                "unprivileged transient login still depends on root-owned mise config"
            )
        if environment.get("TMPDIR") != str(cwd):
            raise AssertionError(
                "transient Context7 login can use temporary files outside its private root"
            )
        if environment.get("XDG_RUNTIME_DIR") != str(cwd):
            raise AssertionError(
                "transient Context7 login can use XDG runtime state outside its private root"
            )
        if environment.get("MISE_CACHE_DIR") != str(cwd / "mise-cache"):
            raise AssertionError(
                "mise cache escaped the transient Context7 login root"
            )
        if environment.get("MISE_TMP_DIR") != str(cwd):
            raise AssertionError(
                "mise temporary state escaped the transient Context7 login root"
            )
        if cwd.exists():
            raise AssertionError(
                "transient Context7 login directory was not removed"
            )
        if package_path.parent.exists():
            raise AssertionError(
                "transient root-controlled Context7 package directory was not removed"
            )


def assert_integrity_mismatch_blocks_vendor_execution(module) -> None:
    original_login_process = module.run_login_process
    original_choose = module.choose_cli_metadata
    original_open_package = module.open_package_url
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_mise_config = module.MISE_CONFIG
    original_setpriv = module.SETPRIV
    executed = False

    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-integrity-test-"
    ) as temp:
        temp_root = Path(temp)
        run_root = temp_root / "run"
        run_root.mkdir(mode=0o755)
        mise_config = temp_root / "mise.toml"
        write_mise_config(mise_config)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.MISE_CONFIG = mise_config
        module.SETPRIV = Path("/bin/true")
        module.choose_cli_metadata = lambda *args, **kwargs: (
            package_metadata(module),
            True,
        )
        module.open_package_url = lambda url, *, environment: PackageResponse(
            b"changed-package-bytes-after-metadata-resolution", url
        )

        def unexpected_execution(*args, **kwargs):
            nonlocal executed
            del args, kwargs
            executed = True

        try:
            module.run_login_process = unexpected_execution
            try:
                module.acquire_api_key(cli_channel="reviewed")
            except module.DeviceLoginError as exc:
                if "sha512 integrity check" not in str(exc):
                    raise AssertionError(
                        f"unexpected integrity mismatch error: {exc}"
                    ) from exc
            else:
                raise AssertionError(
                    "changed Context7 tarball bytes unexpectedly passed integrity verification"
                )
        finally:
            module.run_login_process = original_login_process
            module.choose_cli_metadata = original_choose
            module.open_package_url = original_open_package
            module.RUN_ROOT = original_run_root
            module.NPM = original_npm
            module.MISE_CONFIG = original_mise_config
            module.SETPRIV = original_setpriv

    if executed:
        raise AssertionError(
            "Context7 vendor code executed after the selected tarball failed integrity"
        )


def assert_preexec_package_revalidation(module) -> None:
    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-preexec-test-"
    ) as temp:
        tarball = Path(temp) / "ctx7-0.5.8.tgz"
        tarball.write_bytes(SYNTHETIC_PACKAGE)
        os.chmod(tarball, 0o440)
        if os.geteuid() == 0:
            os.chown(tarball, 0, module.SANDBOX_GID)
            expected_uid = 0
            expected_gid = module.SANDBOX_GID
        else:
            expected_uid = os.geteuid()
            expected_gid = os.getegid()

        module.validate_package_tarball(
            tarball,
            expected_uid=expected_uid,
            expected_gid=expected_gid,
            expected_integrity=SYNTHETIC_INTEGRITY,
        )

        os.chmod(tarball, 0o640)
        tarball.write_bytes(b"X" * len(SYNTHETIC_PACKAGE))
        os.chmod(tarball, 0o440)
        try:
            module.validate_package_tarball(
                tarball,
                expected_uid=expected_uid,
                expected_gid=expected_gid,
                expected_integrity=SYNTHETIC_INTEGRITY,
            )
        except module.DeviceLoginError as exc:
            if "changed after integrity validation" not in str(exc):
                raise AssertionError(
                    f"unexpected pre-execution package error: {exc}"
                ) from exc
        else:
            raise AssertionError(
                "pre-execution verification accepted changed Context7 package bytes"
            )


def assert_node_version_contract(module) -> None:
    original_mise_config = module.MISE_CONFIG
    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-mise-test-"
    ) as temp:
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
                    raise AssertionError(
                        f"invalid bundled Node version was accepted: {invalid!r}"
                    )
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
                raise AssertionError(
                    "read-only Context7 preflight unexpectedly supplied stdin"
                )
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout=state + "\n",
                stderr="",
            )

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
                raise AssertionError(
                    "unsafe/unexpected Context7 preflight state was accepted: "
                    f"{state!r}"
                )
    finally:
        module.subprocess.run = original_run
        module.PYTHON = original_python

    if not captured:
        raise AssertionError("Context7 preflight did not invoke the manager")
    for command in captured:
        if command[-2:] != ["status", "--menu"]:
            raise AssertionError(
                f"Context7 preflight was not read-only: {command!r}"
            )


def assert_success_reaps_process_group(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    captured: dict[str, object] = {}
    signals: list[tuple[int, int]] = []

    class SuccessProcess:
        pid = 313131

        def poll(self):
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
    if kwargs.get("start_new_session") is not True:
        raise AssertionError(
            "successful transient Context7 CLI was not isolated into its own process group"
        )
    if kwargs.get("stdin") != subprocess.DEVNULL:
        raise AssertionError(
            "vendor CLI inherited terminal stdin instead of Remote Dev owning cancellation"
        )
    if kwargs.get("umask") != 0o077:
        raise AssertionError("vendor CLI did not receive umask 077")
    if signals != [(process.pid, signal.SIGKILL)]:
        raise AssertionError(
            f"successful Context7 login left a residual process group: {signals!r}"
        )


def assert_timeout_terminates_process_group(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    original_timeout = module.LOGIN_TIMEOUT_SECONDS
    signals: list[tuple[int, int]] = []

    class TimeoutProcess:
        pid = 424242

        def poll(self):
            return None

        def wait(self, *, timeout):
            del timeout
            return -signal.SIGTERM

    process = TimeoutProcess()

    try:
        module.subprocess.Popen = lambda command, **kwargs: process
        module.os.killpg = lambda pgid, sig: signals.append((pgid, sig))
        module.LOGIN_TIMEOUT_SECONDS = 0
        try:
            with open(os.devnull, encoding="utf-8") as cancel_stream:
                module.run_login_process(
                    ["synthetic-ctx7"],
                    cwd=Path("/tmp"),
                    environment={"PATH": "/usr/bin:/bin"},
                    cancel_stream=cancel_stream,
                )
        except module.DeviceLoginError as exc:
            if "timed out" not in str(exc):
                raise AssertionError(f"unexpected timeout error: {exc}") from exc
        else:
            raise AssertionError(
                "timed-out Context7 device login unexpectedly succeeded"
            )
    finally:
        module.subprocess.Popen = original_popen
        module.os.killpg = original_killpg
        module.LOGIN_TIMEOUT_SECONDS = original_timeout

    expected = [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    if signals != expected:
        raise AssertionError(
            "timed-out Context7 process group was not fully terminated: "
            f"{signals!r}"
        )


def assert_q_cancels_process_group(module) -> None:
    original_popen = module.subprocess.Popen
    original_killpg = module.os.killpg
    original_select = module.select.select
    signals: list[tuple[int, int]] = []

    class WaitingProcess:
        pid = 434343

        def poll(self):
            return None

        def wait(self, *, timeout):
            del timeout
            return -signal.SIGTERM

    class CancelStream:
        def readline(self):
            return "q\n"

    process = WaitingProcess()
    stream = CancelStream()

    try:
        module.subprocess.Popen = lambda command, **kwargs: process
        module.os.killpg = lambda pgid, sig: signals.append((pgid, sig))
        module.select.select = (
            lambda read, write, error, timeout: ([stream], [], [])
        )
        try:
            module.run_login_process(
                ["synthetic-ctx7"],
                cwd=Path("/tmp"),
                environment={"PATH": "/usr/bin:/bin"},
                cancel_stream=stream,
            )
        except module.DeviceLoginError as exc:
            if str(exc) != "cancelled":
                raise AssertionError(
                    f"unexpected cancellation error: {exc}"
                ) from exc
        else:
            raise AssertionError(
                "q cancellation unexpectedly allowed device login to continue"
            )
    finally:
        module.subprocess.Popen = original_popen
        module.os.killpg = original_killpg
        module.select.select = original_select

    expected = [
        (process.pid, signal.SIGTERM),
        (process.pid, signal.SIGKILL),
    ]
    if signals != expected:
        raise AssertionError(
            "cancelled Context7 process group was not fully terminated: "
            f"{signals!r}"
        )


def assert_cleanup_failure_is_fatal(module) -> None:
    original_login_process = module.run_login_process
    original_choose = module.choose_cli_metadata
    original_open_package = module.open_package_url
    original_run_root = module.RUN_ROOT
    original_npm = module.NPM
    original_mise_config = module.MISE_CONFIG
    original_setpriv = module.SETPRIV
    original_rmtree = module.shutil.rmtree
    cleanup_attempts: list[Path] = []

    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-cleanup-test-"
    ) as temp:
        temp_root = Path(temp)
        run_root = temp_root / "run"
        run_root.mkdir(mode=0o755)
        mise_config = temp_root / "mise.toml"
        write_mise_config(mise_config)
        module.RUN_ROOT = run_root
        module.NPM = Path("/bin/true")
        module.MISE_CONFIG = mise_config
        module.SETPRIV = Path("/bin/true")
        module.choose_cli_metadata = lambda *args, **kwargs: (
            package_metadata(module),
            True,
        )
        module.open_package_url = lambda url, *, environment: PackageResponse(
            SYNTHETIC_PACKAGE, url
        )

        def fake_login_process(
            command, *, cwd, environment, cancel_stream=None
        ):
            del command, cwd, cancel_stream
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
            cleanup_attempts.append(Path(path))
            raise OSError(13, "synthetic cleanup failure")

        try:
            module.run_login_process = fake_login_process
            module.shutil.rmtree = fail_rmtree
            try:
                module.acquire_api_key(cli_channel="reviewed")
            except module.DeviceLoginError as exc:
                if (
                    "could not remove transient Context7 CLI/login state"
                    not in str(exc)
                ):
                    raise AssertionError(
                        f"unexpected cleanup error: {exc}"
                    ) from exc
            else:
                raise AssertionError(
                    "Context7 login accepted a failed transient-state cleanup"
                )
        finally:
            module.run_login_process = original_login_process
            module.choose_cli_metadata = original_choose
            module.open_package_url = original_open_package
            module.RUN_ROOT = original_run_root
            module.NPM = original_npm
            module.MISE_CONFIG = original_mise_config
            module.SETPRIV = original_setpriv
            module.shutil.rmtree = original_rmtree

    if len(cleanup_attempts) != 2:
        raise AssertionError(
            "cleanup failure prevented an attempt to remove every transient root: "
            f"{cleanup_attempts!r}"
        )


def assert_credentials_contract(module) -> None:
    original_run_root = module.RUN_ROOT
    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-credentials-test-"
    ) as temp:
        root = Path(temp) / "remote-dev-context7-login-test"
        root.mkdir(mode=0o700)
        run_root = root.parent
        module.RUN_ROOT = run_root
        uid = os.geteuid()
        gid = os.getegid()
        path = root / "config" / module.CONTEXT7_CREDENTIALS_RELATIVE
        config_dir = root / "config"
        credential_dir = path.parent

        valid = {"access_token": SYNTHETIC_KEY, "token_type": "bearer"}
        write_credentials(path, valid, uid=uid, gid=gid)
        if module.read_credentials(root, expected_uid=uid) != SYNTHETIC_KEY:
            raise AssertionError(
                "valid long-lived Context7 API-key state was rejected"
            )

        invalid_payloads = (
            {"access_token": "not-a-context7-key", "token_type": "bearer"},
            {"access_token": "ctx7sk-", "token_type": "bearer"},
            {"access_token": SYNTHETIC_KEY, "token_type": "oauth"},
            {
                "access_token": SYNTHETIC_KEY,
                "token_type": "bearer",
                "refresh_token": "synthetic",
            },
            {
                "access_token": SYNTHETIC_KEY,
                "token_type": "bearer",
                "expires_in": 60,
            },
        )
        for payload in invalid_payloads:
            write_credentials(path, payload, uid=uid, gid=gid)
            try:
                module.read_credentials(root, expected_uid=uid)
            except module.DeviceLoginError:
                pass
            else:
                raise AssertionError(
                    f"unsafe Context7 credential shape was accepted: {payload!r}"
                )

        write_credentials(path, valid, uid=uid, gid=gid)
        os.chmod(config_dir, 0o750)
        try:
            module.read_credentials(root, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError(
                "group-accessible Context7 config directory was accepted"
            )
        os.chmod(config_dir, 0o700)

        os.chmod(credential_dir, 0o705)
        try:
            module.read_credentials(root, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError(
                "world-accessible Context7 credential directory was accepted"
            )
        os.chmod(credential_dir, 0o700)

        os.chmod(path, 0o644)
        try:
            module.read_credentials(root, expected_uid=uid)
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError(
                "group/world-readable Context7 credentials were accepted"
            )

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
            raise AssertionError(
                "Context7 credential reader followed a vendor-controlled parent symlink"
            )
    module.RUN_ROOT = original_run_root


def assert_adoption_order_and_failure(module) -> None:
    original_run_manager = module.run_manager
    original_preflight = module.preflight_manager_state
    original_acquire = module.acquire_api_key
    calls: list[tuple[list[str], str | None]] = []
    preflight_calls = 0

    def fake_manager(
        arguments: list[str], *, input_text: str | None = None
    ) -> None:
        calls.append((list(arguments), input_text))

    def fake_preflight() -> None:
        nonlocal preflight_calls
        preflight_calls += 1

    try:
        module.run_manager = fake_manager
        module.preflight_manager_state = fake_preflight
        module.acquire_api_key = lambda *, cli_channel: (
            SYNTHETIC_KEY,
            "0.5.8",
            True,
        )
        if module.command_login(yes=True, cli_channel="reviewed") != 0:
            raise AssertionError(
                "synthetic device login command unexpectedly failed"
            )
    finally:
        module.run_manager = original_run_manager
        module.preflight_manager_state = original_preflight
        module.acquire_api_key = original_acquire

    expected = [
        (["repair", "--yes", "--api-key-stdin"], SYNTHETIC_KEY + "\n")
    ]
    if calls != expected or preflight_calls != 1:
        raise AssertionError(
            "unexpected device-login adoption sequence: "
            f"preflight={preflight_calls}, calls={calls!r}"
        )

    calls.clear()
    preflight_calls = 0

    def fail_acquire(*, cli_channel):
        del cli_channel
        raise module.DeviceLoginError("synthetic login failure")

    try:
        module.run_manager = fake_manager
        module.preflight_manager_state = fake_preflight
        module.acquire_api_key = fail_acquire
        try:
            module.command_login(yes=True, cli_channel="reviewed")
        except module.DeviceLoginError:
            pass
        else:
            raise AssertionError(
                "synthetic device-login failure unexpectedly succeeded"
            )
    finally:
        module.run_manager = original_run_manager
        module.preflight_manager_state = original_preflight
        module.acquire_api_key = original_acquire

    if calls or preflight_calls != 1:
        raise AssertionError(
            "failed/cancelled device login mutated managed Context7 state "
            "instead of preserving it"
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
            raise AssertionError(
                "Context7 device login accepted a non-Codex role"
            )
    finally:
        if previous is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = previous


def assert_package_download_total_deadline(module) -> None:
    original_open = module.open_package_url
    original_timeout = module.PACKAGE_TIMEOUT_SECONDS

    class SlowResponse(PackageResponse):
        def read(self, size: int) -> bytes:
            time.sleep(0.2)
            return super().read(size)

    with tempfile.TemporaryDirectory(
        prefix="remote-dev-context7-deadline-test-"
    ) as temp:
        root = Path(temp)
        metadata = package_metadata(module)
        module.open_package_url = lambda url, *, environment: SlowResponse(
            SYNTHETIC_PACKAGE, url
        )
        module.PACKAGE_TIMEOUT_SECONDS = 0.05
        started = time.monotonic()
        try:
            try:
                module.download_verified_package(
                    metadata,
                    root=root,
                    gid=os.getegid(),
                    environment={},
                )
            except module.DeviceLoginError as exc:
                if "total deadline" not in str(exc):
                    raise AssertionError(
                        f"unexpected package deadline error: {exc}"
                    ) from exc
            else:
                raise AssertionError(
                    "slow Context7 package download exceeded its total deadline"
                )
        finally:
            module.open_package_url = original_open
            module.PACKAGE_TIMEOUT_SECONDS = original_timeout
        if time.monotonic() - started >= 0.15:
            raise AssertionError(
                "Context7 package deadline did not interrupt a blocking slow read"
            )
        if any(root.iterdir()):
            raise AssertionError(
                "timed-out Context7 package download left partial bytes"
            )


def main() -> int:
    module = load_helper()
    assert_reviewed_version_contract(module)
    assert_repo_version_pin_sync(module)
    assert_node_version_contract(module)
    assert_package_metadata_contract(module)
    assert_metadata_timeout_is_bounded(module)
    assert_reviewed_latest_selection(module)
    assert_manager_preflight_is_read_only(module)
    assert_acquire_uses_isolated_environment(module)
    assert_integrity_mismatch_blocks_vendor_execution(module)
    assert_preexec_package_revalidation(module)
    assert_success_reaps_process_group(module)
    assert_timeout_terminates_process_group(module)
    assert_q_cancels_process_group(module)
    assert_cleanup_failure_is_fatal(module)
    assert_credentials_contract(module)
    assert_adoption_order_and_failure(module)
    assert_package_download_total_deadline(module)
    assert_role_gate(module)
    print(
        "Context7 device-login isolation/version/integrity/cancellation regressions: OK"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
