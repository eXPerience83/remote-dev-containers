#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import tomllib


CONTEXT7_CLI_PACKAGE = "ctx7@0.5.7"
CONTEXT7_KEY_PREFIX = "ctx7sk-"
CONTEXT7_CREDENTIALS_RELATIVE = Path("context7") / "credentials.json"
NPM_REGISTRY = "https://registry.npmjs.org/"
NPM = Path("/opt/remote-dev/mise/shims/npm")
MISE_CONFIG = Path("/etc/mise/mise.toml")
SETPRIV = Path("/usr/bin/setpriv")
PYTHON = Path("/opt/remote-dev/mise/shims/python")
MANAGER = Path("/usr/local/lib/remote-dev/remote-dev-context7.py")
RUN_ROOT = Path("/run")
MAX_CREDENTIAL_BYTES = 32 * 1024
LOGIN_TIMEOUT_SECONDS = 15 * 60
PROCESS_TERMINATION_GRACE_SECONDS = 5
SANDBOX_UID = 65534
SANDBOX_GID = 65534
PREFLIGHT_ALLOWED_STATES = {
    "Context7: not configured",
    "Context7: configured (API key stored)",
    "Context7: configured (anonymous)",
}
PREFLIGHT_UNMANAGED_STATE = "Context7: unmanaged configuration (Remote Dev will not modify)"


class DeviceLoginError(RuntimeError):
    pass


def validate_role() -> None:
    role = os.environ.get("REMOTE_DEV_ROLE", "codex")
    if role != "codex":
        raise DeviceLoginError(
            f"Context7 device login is available only for REMOTE_DEV_ROLE=codex; got {role}"
        )


def confirm(*, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        raise DeviceLoginError("Context7 device login requires interactive confirmation or --yes")
    print(
        "Context7 is an optional external service operated by Upstash. "
        "This sign-in downloads and runs a transient official Context7 CLI package, "
        "then performs an explicit device-login network flow.",
        file=sys.stderr,
    )
    print(
        "Only the resulting Context7 API key is adopted into Remote Dev private state; "
        "the transient CLI, its login state and npm cache are removed afterward.",
        file=sys.stderr,
    )
    answer = input("Sign in to Context7? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise DeviceLoginError("cancelled")


def validate_executable(path: Path, *, label: str) -> None:
    try:
        info = path.stat()
    except OSError as exc:
        raise DeviceLoginError(f"{label} is unavailable: errno {exc.errno}") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise DeviceLoginError(f"{label} is not an executable regular file: {path}")


def configured_node_version() -> str:
    try:
        with MISE_CONFIG.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeviceLoginError("bundled Node runtime configuration is unavailable") from exc

    tools = config.get("tools")
    version = tools.get("node") if isinstance(tools, dict) else None
    if not isinstance(version, str):
        raise DeviceLoginError("bundled Node runtime version is missing from mise configuration")
    parts = version.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise DeviceLoginError("bundled Node runtime version has an unexpected format")
    return version


def validate_run_root() -> None:
    try:
        info = RUN_ROOT.lstat()
    except OSError as exc:
        raise DeviceLoginError(f"transient runtime root is unavailable: errno {exc.errno}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise DeviceLoginError(f"transient runtime root must be a real directory: {RUN_ROOT}")
    if not os.access(RUN_ROOT, os.W_OK | os.X_OK):
        raise DeviceLoginError(f"transient runtime root is not writable: {RUN_ROOT}")


def sandbox_identity() -> tuple[int, int]:
    if os.geteuid() == 0:
        return SANDBOX_UID, SANDBOX_GID
    return os.geteuid(), os.getegid()


def create_login_root(uid: int, gid: int) -> Path:
    validate_run_root()
    try:
        root = Path(tempfile.mkdtemp(prefix="remote-dev-context7-login-", dir=RUN_ROOT))
        os.chmod(root, 0o700)
        if os.geteuid() == 0:
            os.chown(root, uid, gid)
    except OSError as exc:
        raise DeviceLoginError(f"could not create transient Context7 login state: errno {exc.errno}") from exc
    return root


def remove_login_root(root: Path) -> None:
    if root.parent != RUN_ROOT or not root.name.startswith("remote-dev-context7-login-"):
        raise DeviceLoginError("refusing to remove an unexpected transient Context7 login path")
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeviceLoginError(
            f"could not remove transient Context7 CLI/login state: errno {exc.errno}"
        ) from exc


def transient_environment(root: Path, *, node_version: str) -> dict[str, str]:
    environment = {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "XDG_RUNTIME_DIR": str(root),
        "TMPDIR": str(root),
        "npm_config_cache": str(root / "npm-cache"),
        "npm_config_registry": NPM_REGISTRY,
        "npm_config_userconfig": str(root / "npm-user.conf"),
        "npm_config_globalconfig": str(root / "npm-global.conf"),
        "npm_config_ignore_scripts": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "CTX7_TELEMETRY_DISABLED": "1",
        "DO_NOT_TRACK": "1",
        "PATH": "/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin",
        "MISE_DATA_DIR": "/opt/remote-dev/mise",
        "MISE_CACHE_DIR": str(root / "mise-cache"),
        "MISE_TMP_DIR": str(root),
        "MISE_NODE_VERSION": node_version,
        "MISE_OFFLINE": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": os.environ.get("TERM", "xterm-256color"),
    }
    ca_certificate = os.environ.get("NODE_EXTRA_CA_CERTS", "")
    if ca_certificate:
        environment["NODE_EXTRA_CA_CERTS"] = ca_certificate
    return environment


def login_command(uid: int, gid: int) -> list[str]:
    command = [
        str(NPM),
        "exec",
        "--yes",
        "--ignore-scripts",
        f"--registry={NPM_REGISTRY}",
        f"--package={CONTEXT7_CLI_PACKAGE}",
        "--",
        "ctx7",
        "login",
        "--no-browser",
    ]
    if os.geteuid() != 0:
        return command
    validate_executable(SETPRIV, label="setpriv")
    return [
        str(SETPRIV),
        "--reuid",
        str(uid),
        "--regid",
        str(gid),
        "--clear-groups",
        "--no-new-privs",
        *command,
    ]


def kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise DeviceLoginError(
            f"could not kill the transient Context7 CLI process group: errno {exc.errno}"
        ) from exc


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as exc:
        raise DeviceLoginError(
            f"could not terminate the transient Context7 CLI process group: errno {exc.errno}"
        ) from exc

    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass

    # The npm parent can exit before a descendant. Always address the process
    # group again so a child that survived SIGTERM cannot keep polling after a
    # timeout or cancellation.
    kill_process_group(process)
    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise DeviceLoginError("transient Context7 CLI did not terminate after SIGKILL") from exc


def run_login_process(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    # Vendor-created credential files and directories must be private from the
    # instant they are created, not tightened only after privileged adoption.
    previous_umask = os.umask(0o077)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        raise DeviceLoginError(f"could not start the transient Context7 CLI: errno {exc.errno}") from exc
    finally:
        os.umask(previous_umask)

    try:
        returncode = process.wait(timeout=LOGIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        raise DeviceLoginError("Context7 device login timed out") from exc
    except KeyboardInterrupt:
        terminate_process_group(process)
        raise

    # `npm exec` is expected to wait for ctx7, but the vendor execution boundary
    # is transient even if changed package code daemonizes a descendant. Kill any
    # process that remains in the isolated group after the parent exits.
    kill_process_group(process)
    if returncode != 0:
        raise DeviceLoginError(f"Context7 device login failed (exit {returncode})")


def open_owned_directory_at(parent_fd: int, name: str, *, expected_uid: int, label: str) -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise DeviceLoginError(f"{label} is unavailable or unsafe: errno {exc.errno}") from exc
    info = os.fstat(fd)
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != expected_uid
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        os.close(fd)
        raise DeviceLoginError(f"{label} has unsafe ownership, type or permissions")
    return fd


def read_credentials(root: Path, *, expected_uid: int) -> str:
    if root.parent != RUN_ROOT or not root.name.startswith("remote-dev-context7-login-"):
        raise DeviceLoginError("refusing an unexpected transient Context7 credential root")

    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    key_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    root_fd: int | None = None
    config_fd: int | None = None
    context7_fd: int | None = None
    key_fd: int | None = None
    try:
        try:
            root_fd = os.open(root, directory_flags)
        except OSError as exc:
            raise DeviceLoginError(f"Context7 login root is unavailable or unsafe: errno {exc.errno}") from exc
        root_info = os.fstat(root_fd)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != expected_uid
            or stat.S_IMODE(root_info.st_mode) & 0o077
        ):
            raise DeviceLoginError("Context7 login root has unsafe ownership, type or permissions")

        config_fd = open_owned_directory_at(
            root_fd,
            "config",
            expected_uid=expected_uid,
            label="Context7 login config directory",
        )
        context7_fd = open_owned_directory_at(
            config_fd,
            "context7",
            expected_uid=expected_uid,
            label="Context7 login credential directory",
        )
        try:
            key_fd = os.open("credentials.json", key_flags, dir_fd=context7_fd)
        except OSError as exc:
            raise DeviceLoginError(f"Context7 login credentials are unavailable or unsafe: errno {exc.errno}") from exc

        info = os.fstat(key_fd)
        if not stat.S_ISREG(info.st_mode):
            raise DeviceLoginError("Context7 login credentials are not a regular file")
        if info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) & 0o077:
            raise DeviceLoginError("Context7 login credentials have unsafe ownership or permissions")
        if info.st_size <= 0 or info.st_size > MAX_CREDENTIAL_BYTES:
            raise DeviceLoginError("Context7 login credentials exceed the supported size boundary")

        chunks: list[bytes] = []
        remaining = MAX_CREDENTIAL_BYTES + 1
        while remaining > 0:
            chunk = os.read(key_fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if not data or len(data) > MAX_CREDENTIAL_BYTES:
            raise DeviceLoginError("Context7 login credentials exceed the supported size boundary")
    finally:
        for fd in (key_fd, context7_fd, config_fd, root_fd):
            if fd is not None:
                os.close(fd)

    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeviceLoginError("Context7 login credentials are not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise DeviceLoginError("Context7 login credentials have an unexpected shape")

    access_token = decoded.get("access_token")
    token_type = decoded.get("token_type")
    if (
        not isinstance(access_token, str)
        or not access_token.startswith(CONTEXT7_KEY_PREFIX)
        or len(access_token) <= len(CONTEXT7_KEY_PREFIX)
    ):
        raise DeviceLoginError("Context7 login did not return the expected long-lived API-key format")
    if not isinstance(token_type, str) or token_type.lower() != "bearer":
        raise DeviceLoginError("Context7 login returned an unexpected credential type")
    if decoded.get("refresh_token"):
        raise DeviceLoginError("Context7 login returned refresh-token state instead of the reviewed API-key flow")
    if decoded.get("expires_in") is not None or decoded.get("expires_at") is not None:
        raise DeviceLoginError("Context7 login returned expiring state instead of the reviewed API-key flow")
    if access_token != access_token.strip() or any(character.isspace() for character in access_token):
        raise DeviceLoginError("Context7 login returned an invalid API-key value")
    return access_token


def preflight_manager_state() -> None:
    validate_executable(PYTHON, label="Python")
    try:
        result = subprocess.run(
            [str(PYTHON), str(MANAGER), "status", "--menu"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise DeviceLoginError(f"could not inspect the current Context7 state: errno {exc.errno}") from exc

    state = result.stdout.strip()
    if result.returncode != 0:
        raise DeviceLoginError("existing Context7 managed state is unsafe or damaged")
    if state == PREFLIGHT_UNMANAGED_STATE:
        raise DeviceLoginError("existing Context7 configuration is unmanaged; Remote Dev will not overwrite it")
    if state not in PREFLIGHT_ALLOWED_STATES:
        raise DeviceLoginError("Context7 manager returned an unexpected preflight state")


def acquire_api_key() -> str:
    validate_executable(NPM, label="npm")
    node_version = configured_node_version()
    uid, gid = sandbox_identity()
    root = create_login_root(uid, gid)
    environment = transient_environment(root, node_version=node_version)
    command = login_command(uid, gid)
    api_key = ""
    try:
        run_login_process(command, cwd=root, environment=environment)
        api_key = read_credentials(root, expected_uid=uid)
    finally:
        remove_login_root(root)
    return api_key


def run_manager(arguments: list[str], *, input_text: str | None = None) -> None:
    validate_executable(PYTHON, label="Python")
    try:
        result = subprocess.run(
            [str(PYTHON), str(MANAGER), *arguments],
            input=input_text,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise DeviceLoginError(f"could not invoke the Context7 manager: errno {exc.errno}") from exc
    if result.returncode != 0:
        raise DeviceLoginError(f"Context7 manager rejected the operation (exit {result.returncode})")


def command_login(*, yes: bool) -> int:
    confirm(yes=yes)

    # Validate the current ownership/configuration boundary without changing it.
    # A failed or cancelled vendor login must not rewrite config or authentication state.
    preflight_manager_state()

    api_key = acquire_api_key()

    # The key is transferred only over the child process stdin. It is never a
    # command-line argument, environment variable, log line or temporary TOML value.
    run_manager(["repair", "--yes", "--api-key-stdin"], input_text=api_key + "\n")
    print("Context7 device login: API key adopted into Remote Dev private state")
    print("Transient Context7 CLI/login state: removed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="remote-dev-context7-device-login",
        description="Sign in to Context7 through a transient isolated device-code flow.",
    )
    parser.add_argument("--yes", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_role()
        return command_login(yes=args.yes)
    except DeviceLoginError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("ERROR: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())