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


CONTEXT7_CLI_PACKAGE = "ctx7@0.5.7"
CONTEXT7_KEY_PREFIX = "ctx7sk-"
CONTEXT7_CREDENTIALS_RELATIVE = Path("context7") / "credentials.json"
NPM_REGISTRY = "https://registry.npmjs.org/"
NPM = Path("/opt/remote-dev/mise/shims/npm")
SETPRIV = Path("/usr/bin/setpriv")
PYTHON = Path("/opt/remote-dev/mise/shims/python")
MANAGER = Path("/usr/local/lib/remote-dev/remote-dev-context7.py")
RUN_ROOT = Path("/run")
MAX_CREDENTIAL_BYTES = 32 * 1024
LOGIN_TIMEOUT_SECONDS = 15 * 60
PROCESS_TERMINATION_GRACE_SECONDS = 5
SANDBOX_UID = 65534
SANDBOX_GID = 65534


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


def transient_environment(root: Path) -> dict[str, str]:
    environment = {
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_STATE_HOME": str(root / "state"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "npm_config_cache": str(root / "npm-cache"),
        "npm_config_registry": NPM_REGISTRY,
        "npm_config_userconfig": "/dev/null",
        "npm_config_globalconfig": "/dev/null",
        "npm_config_ignore_scripts": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "CTX7_TELEMETRY_DISABLED": "1",
        "DO_NOT_TRACK": "1",
        "PATH": "/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin",
        "MISE_DATA_DIR": "/opt/remote-dev/mise",
        "MISE_CACHE_DIR": "/opt/remote-dev/mise-cache",
        "MISE_CONFIG_DIR": "/etc/mise",
        "MISE_GLOBAL_CONFIG_FILE": "/etc/mise/mise.toml",
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
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise DeviceLoginError(
            f"could not kill the transient Context7 CLI process group: errno {exc.errno}"
        ) from exc

    try:
        process.wait(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise DeviceLoginError("transient Context7 CLI did not terminate after SIGKILL") from exc


def run_login_process(command: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        raise DeviceLoginError(f"could not start the transient Context7 CLI: errno {exc.errno}") from exc

    try:
        returncode = process.wait(timeout=LOGIN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        terminate_process_group(process)
        raise DeviceLoginError("Context7 device login timed out") from exc
    except KeyboardInterrupt:
        terminate_process_group(process)
        raise

    if returncode != 0:
        raise DeviceLoginError(f"Context7 device login failed (exit {returncode})")


def read_credentials(path: Path, *, expected_uid: int) -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DeviceLoginError(f"Context7 login credentials are unavailable: errno {exc.errno}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise DeviceLoginError("Context7 login credentials are not a regular file")
        if info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) & 0o077:
            raise DeviceLoginError("Context7 login credentials have unsafe ownership or permissions")
        if info.st_size <= 0 or info.st_size > MAX_CREDENTIAL_BYTES:
            raise DeviceLoginError("Context7 login credentials exceed the supported size boundary")

        chunks: list[bytes] = []
        remaining = MAX_CREDENTIAL_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if not data or len(data) > MAX_CREDENTIAL_BYTES:
            raise DeviceLoginError("Context7 login credentials exceed the supported size boundary")
    finally:
        os.close(fd)

    try:
        decoded = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeviceLoginError("Context7 login credentials are not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise DeviceLoginError("Context7 login credentials have an unexpected shape")

    access_token = decoded.get("access_token")
    token_type = decoded.get("token_type")
    if not isinstance(access_token, str) or not access_token.startswith(CONTEXT7_KEY_PREFIX):
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


def acquire_api_key() -> str:
    validate_executable(NPM, label="npm")
    uid, gid = sandbox_identity()
    root = create_login_root(uid, gid)
    environment = transient_environment(root)
    credentials = Path(environment["XDG_CONFIG_HOME"]) / CONTEXT7_CREDENTIALS_RELATIVE
    command = login_command(uid, gid)
    api_key = ""
    try:
        run_login_process(command, cwd=root, environment=environment)
        api_key = read_credentials(credentials, expected_uid=uid)
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

    # Preflight the existing ownership/configuration boundary before any vendor
    # package is downloaded. This preserves a current key and creates only the
    # already-reviewed anonymous managed block when the integration was absent.
    run_manager(["repair", "--yes"])

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
