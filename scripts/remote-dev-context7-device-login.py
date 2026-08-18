#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import select
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request


CONTEXT7_CLI_NAME = "ctx7"
CONTEXT7_KEY_PREFIX = "ctx7sk-"
CONTEXT7_CREDENTIALS_RELATIVE = Path("context7") / "credentials.json"
REVIEWED_CONTEXT7_CLI_VERSION = "0.5.8"
REVIEWED_CONTEXT7_CLI_INTEGRITY = (
    "sha512-D7yDKDH1K8f4A4e0N8pFx3sfFi0IwiLt167P2p3yp++ruHeo3i2yycH8WdcG35VCzFF95XDWmyPcdOjX9xxtoA=="
)
EXPECTED_PACKAGE_LICENSE = "MIT"
NPM_REGISTRY = "https://registry.npmjs.org/"
NPM_REGISTRY_HOST = "registry.npmjs.org"
NPM = Path("/opt/remote-dev/mise/shims/npm")
MISE_CONFIG = Path("/etc/mise/mise.toml")
SETPRIV = Path("/usr/bin/setpriv")
PYTHON = Path("/opt/remote-dev/mise/shims/python")
MANAGER = Path("/usr/local/lib/remote-dev/remote-dev-context7.py")
RUN_ROOT = Path("/run")
MAX_CREDENTIAL_BYTES = 32 * 1024
MAX_METADATA_BYTES = 32 * 1024
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
LOGIN_TIMEOUT_SECONDS = 15 * 60
METADATA_TIMEOUT_SECONDS = 30
PACKAGE_TIMEOUT_SECONDS = 60
PROCESS_TERMINATION_GRACE_SECONDS = 5
PROCESS_POLL_SECONDS = 0.25
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


class NoPackageRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject package redirects so selected npm metadata stays authoritative."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        return None


@contextlib.contextmanager
def package_download_deadline():
    deadline = time.monotonic() + PACKAGE_TIMEOUT_SECONDS
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    started = time.monotonic()

    def deadline_expired(signum, frame):
        del signum, frame
        raise DeviceLoginError("selected Context7 package download exceeded the total deadline")

    signal.signal(signal.SIGALRM, deadline_expired)
    signal.setitimer(signal.ITIMER_REAL, PACKAGE_TIMEOUT_SECONDS)
    try:
        yield deadline
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            elapsed = time.monotonic() - started
            restored = max(0.000001, previous_timer[0] - elapsed)
            signal.setitimer(signal.ITIMER_REAL, restored, previous_timer[1])


def require_deadline_remaining(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise DeviceLoginError("selected Context7 package download exceeded the total deadline")


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


def exact_version(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise DeviceLoginError(f"Context7 CLI version has an unexpected format: {value!r}")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    exact_version(value)
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def reviewed_cli_version() -> str:
    return exact_version(REVIEWED_CONTEXT7_CLI_VERSION)


def reviewed_cli_integrity() -> str:
    parse_sha512_integrity(REVIEWED_CONTEXT7_CLI_INTEGRITY)
    return REVIEWED_CONTEXT7_CLI_INTEGRITY


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


def create_package_root(gid: int) -> Path:
    validate_run_root()
    owner_uid = 0 if os.geteuid() == 0 else os.geteuid()
    try:
        root = Path(tempfile.mkdtemp(prefix="remote-dev-context7-package-", dir=RUN_ROOT))
        os.chmod(root, 0o750)
        if os.geteuid() == 0:
            os.chown(root, owner_uid, gid)
    except OSError as exc:
        raise DeviceLoginError(
            f"could not create transient Context7 package state: errno {exc.errno}"
        ) from exc
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


def remove_package_root(root: Path) -> None:
    if root.parent != RUN_ROOT or not root.name.startswith("remote-dev-context7-package-"):
        raise DeviceLoginError("refusing to remove an unexpected transient Context7 package path")
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise DeviceLoginError(
            f"could not remove transient Context7 package state: errno {exc.errno}"
        ) from exc


def remove_transient_roots(login_root: Path, package_root: Path) -> None:
    errors: list[DeviceLoginError] = []
    for remover, root in (
        (remove_login_root, login_root),
        (remove_package_root, package_root),
    ):
        try:
            remover(root)
        except DeviceLoginError as exc:
            errors.append(exc)
    if errors:
        raise errors[0]


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


def privileged_prefix(uid: int, gid: int) -> list[str]:
    if os.geteuid() != 0:
        return []
    validate_executable(SETPRIV, label="setpriv")
    return [
        str(SETPRIV),
        "--reuid",
        str(uid),
        "--regid",
        str(gid),
        "--clear-groups",
        "--no-new-privs",
    ]


def npm_json(
    arguments: list[str],
    *,
    uid: int,
    gid: int,
    cwd: Path,
    environment: dict[str, str],
) -> object:
    deadline = time.monotonic() + METADATA_TIMEOUT_SECONDS
    command = [
        *privileged_prefix(uid, gid),
        str(NPM),
        *arguments,
        f"--registry={NPM_REGISTRY}",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(0.001, deadline - time.monotonic()),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeviceLoginError("could not resolve official Context7 npm metadata") from exc
    if result.returncode != 0:
        raise DeviceLoginError(
            f"official Context7 npm metadata lookup failed (exit {result.returncode})"
        )
    if time.monotonic() >= deadline:
        raise DeviceLoginError("official Context7 npm metadata lookup exceeded the total deadline")
    if len(result.stdout) > MAX_METADATA_BYTES or len(result.stderr) > MAX_METADATA_BYTES:
        raise DeviceLoginError("official Context7 npm metadata exceeded the supported size boundary")
    try:
        return json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeviceLoginError("official Context7 npm metadata is not valid JSON") from exc


def parse_sha512_integrity(value: object) -> bytes:
    if not isinstance(value, str) or not value.startswith("sha512-"):
        raise DeviceLoginError("official Context7 npm metadata has no supported package integrity")
    encoded = value.removeprefix("sha512-")
    if not encoded or any(character.isspace() for character in encoded):
        raise DeviceLoginError("official Context7 npm metadata has no supported package integrity")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DeviceLoginError("official Context7 npm metadata has malformed sha512 integrity") from exc
    if len(decoded) != hashlib.sha512().digest_size:
        raise DeviceLoginError("official Context7 npm metadata has malformed sha512 integrity")
    return decoded


def exact_tarball_url(version: str) -> str:
    exact_version(version)
    return f"{NPM_REGISTRY}{CONTEXT7_CLI_NAME}/-/{CONTEXT7_CLI_NAME}-{version}.tgz"


def resolve_package_metadata(
    specifier: str,
    *,
    uid: int,
    gid: int,
    cwd: Path,
    environment: dict[str, str],
) -> dict[str, str]:
    payload = npm_json(
        [
            "view",
            f"{CONTEXT7_CLI_NAME}@{specifier}",
            "name",
            "version",
            "license",
            "dist.integrity",
            "dist.tarball",
            "--json",
        ],
        uid=uid,
        gid=gid,
        cwd=cwd,
        environment=environment,
    )
    if isinstance(payload, list):
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise DeviceLoginError("official Context7 npm metadata has an unexpected shape")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise DeviceLoginError("official Context7 npm metadata has an unexpected shape")
    name = payload.get("name")
    version = payload.get("version")
    license_name = payload.get("license")
    integrity = payload.get("dist.integrity")
    tarball = payload.get("dist.tarball")
    if name != CONTEXT7_CLI_NAME or not isinstance(version, str):
        raise DeviceLoginError("official Context7 npm metadata has an unexpected package identity")
    exact_version(version)
    if license_name != EXPECTED_PACKAGE_LICENSE:
        raise DeviceLoginError(
            f"Context7 CLI package license changed from the reviewed {EXPECTED_PACKAGE_LICENSE} contract"
        )
    parse_sha512_integrity(integrity)
    if not isinstance(tarball, str) or tarball != exact_tarball_url(version):
        raise DeviceLoginError("official Context7 npm metadata has an unexpected package tarball URL")
    if specifier != "latest" and version != exact_version(specifier):
        raise DeviceLoginError("official Context7 npm registry did not resolve the requested exact version")
    return {
        "name": name,
        "version": version,
        "license": license_name,
        "integrity": integrity,
        "tarball": tarball,
    }


def validate_reviewed_metadata(metadata: dict[str, str]) -> None:
    if metadata.get("version") != reviewed_cli_version():
        raise DeviceLoginError("official Context7 npm metadata does not match the reviewed version")
    if metadata.get("integrity") != reviewed_cli_integrity():
        raise DeviceLoginError(
            "official Context7 npm integrity does not match the Remote Dev-reviewed artifact"
        )


def choose_cli_metadata(
    channel: str,
    *,
    uid: int,
    gid: int,
    cwd: Path,
    environment: dict[str, str],
) -> tuple[dict[str, str], bool]:
    reviewed = reviewed_cli_version()

    if channel == "reviewed":
        metadata = resolve_package_metadata(
            reviewed, uid=uid, gid=gid, cwd=cwd, environment=environment
        )
        validate_reviewed_metadata(metadata)
        return metadata, True

    try:
        latest = resolve_package_metadata(
            "latest", uid=uid, gid=gid, cwd=cwd, environment=environment
        )
    except DeviceLoginError:
        if channel == "latest":
            raise
        print(
            "Context7 CLI: latest official is unavailable because its metadata failed "
            "mandatory validation; using the Remote Dev-reviewed version.",
            file=sys.stderr,
        )
        metadata = resolve_package_metadata(
            reviewed, uid=uid, gid=gid, cwd=cwd, environment=environment
        )
        validate_reviewed_metadata(metadata)
        return metadata, True
    latest_version = latest["version"]
    if channel == "latest":
        is_reviewed = latest_version == reviewed
        if is_reviewed:
            validate_reviewed_metadata(latest)
        return latest, is_reviewed

    if latest_version == reviewed:
        validate_reviewed_metadata(latest)
        print(f"Context7 CLI: {reviewed} (latest official; reviewed by Remote Dev)")
        return latest, True

    if version_tuple(latest_version) < version_tuple(reviewed):
        print(
            f"Context7 CLI: official npm latest {latest_version} is older than "
            f"Remote Dev-reviewed {reviewed}; using reviewed {reviewed}.",
            file=sys.stderr,
        )
        metadata = resolve_package_metadata(
            reviewed, uid=uid, gid=gid, cwd=cwd, environment=environment
        )
        validate_reviewed_metadata(metadata)
        return metadata, True

    print("Context7 CLI version")
    print("====================")
    print(f"Reviewed by Remote Dev: {reviewed}")
    print(f"Latest official npm:   {latest_version}")
    print("")
    print(f"1) Use reviewed {reviewed} (recommended)")
    print(
        f"2) Use latest official {latest_version} "
        "[official source; Remote Dev review pending]"
    )
    print("3) Cancel")

    if not sys.stdin.isatty():
        print(
            f"Non-interactive device login defaults to reviewed {reviewed}; "
            "use --cli-channel latest to request the latest official version.",
            file=sys.stderr,
        )
        metadata = resolve_package_metadata(
            reviewed, uid=uid, gid=gid, cwd=cwd, environment=environment
        )
        validate_reviewed_metadata(metadata)
        return metadata, True

    choice = input("> ").strip()
    if choice == "1":
        metadata = resolve_package_metadata(
            reviewed, uid=uid, gid=gid, cwd=cwd, environment=environment
        )
        validate_reviewed_metadata(metadata)
        return metadata, True
    if choice == "2":
        return latest, False
    if choice == "3":
        raise DeviceLoginError("cancelled")
    raise DeviceLoginError("invalid Context7 CLI version choice")


def package_ssl_context(environment: dict[str, str]) -> ssl.SSLContext:
    context = ssl.create_default_context()
    ca_certificate = environment.get("NODE_EXTRA_CA_CERTS", "")
    if ca_certificate:
        try:
            context.load_verify_locations(cafile=ca_certificate)
        except (OSError, ssl.SSLError) as exc:
            raise DeviceLoginError("configured extra CA certificate is unavailable or invalid") from exc
    return context


def open_package_url(url: str, *, environment: dict[str, str]):
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != NPM_REGISTRY_HOST
        or parsed.port not in {None, 443}
    ):
        raise DeviceLoginError("refusing to download Context7 package outside the fixed npm origin")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "remote-dev-containers-context7-device-login"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        NoPackageRedirectHandler(),
        urllib.request.HTTPSHandler(context=package_ssl_context(environment)),
    )
    try:
        return opener.open(request, timeout=PACKAGE_TIMEOUT_SECONDS)
    except (OSError, urllib.error.URLError, ssl.SSLError) as exc:
        raise DeviceLoginError("could not download the selected Context7 npm package") from exc


def download_verified_package(
    metadata: dict[str, str],
    *,
    root: Path,
    gid: int,
    environment: dict[str, str],
) -> Path:
    version = exact_version(metadata["version"])
    tarball_url = metadata.get("tarball", "")
    if tarball_url != exact_tarball_url(version):
        raise DeviceLoginError("selected Context7 package tarball no longer matches validated metadata")
    expected_digest = parse_sha512_integrity(metadata.get("integrity"))
    destination = root / f"{CONTEXT7_CLI_NAME}-{version}.tgz"
    digest = hashlib.sha512()
    total = 0
    try:
        with package_download_deadline() as deadline:
            response = open_package_url(tarball_url, environment=environment)
            with response:
                if response.geturl() != tarball_url:
                    raise DeviceLoginError("selected Context7 package redirected unexpectedly")
                with destination.open("xb") as handle:
                    while True:
                        require_deadline_remaining(deadline)
                        chunk = response.read(64 * 1024)
                        require_deadline_remaining(deadline)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_PACKAGE_BYTES:
                            raise DeviceLoginError(
                                "selected Context7 package exceeded the supported size boundary"
                            )
                        digest.update(chunk)
                        handle.write(chunk)
    except DeviceLoginError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise DeviceLoginError(
            f"could not stage the selected Context7 npm package: errno {exc.errno}"
        ) from exc

    if total <= 0:
        destination.unlink(missing_ok=True)
        raise DeviceLoginError("selected Context7 npm package was empty")
    if not hmac.compare_digest(digest.digest(), expected_digest):
        destination.unlink(missing_ok=True)
        raise DeviceLoginError(
            "selected Context7 npm package failed the validated sha512 integrity check"
        )
    try:
        os.chmod(destination, 0o440)
        if os.geteuid() == 0:
            os.chown(destination, 0, gid)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise DeviceLoginError(
            f"could not secure the selected Context7 npm package: errno {exc.errno}"
        ) from exc
    return destination


def validate_package_tarball(
    path: Path,
    *,
    expected_uid: int,
    expected_gid: int,
    expected_integrity: str,
) -> None:
    expected_digest = parse_sha512_integrity(expected_integrity)
    try:
        info = path.lstat()
    except OSError as exc:
        raise DeviceLoginError(f"verified Context7 package is unavailable: errno {exc.errno}") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != expected_uid
        or info.st_gid != expected_gid
        or stat.S_IMODE(info.st_mode) != 0o440
        or info.st_size <= 0
        or info.st_size > MAX_PACKAGE_BYTES
    ):
        raise DeviceLoginError("verified Context7 package has unsafe ownership, type, permissions or size")

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise DeviceLoginError(f"verified Context7 package is unavailable: errno {exc.errno}") from exc
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != info.st_dev
            or opened.st_ino != info.st_ino
            or opened.st_uid != expected_uid
            or opened.st_gid != expected_gid
            or stat.S_IMODE(opened.st_mode) != 0o440
            or opened.st_size != info.st_size
        ):
            raise DeviceLoginError("verified Context7 package changed before execution")
        digest = hashlib.sha512()
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(fd)
    if not hmac.compare_digest(digest.digest(), expected_digest):
        raise DeviceLoginError("verified Context7 package changed after integrity validation")


def login_command(uid: int, gid: int, *, package_tarball: Path) -> list[str]:
    command = [
        str(NPM),
        "exec",
        "--yes",
        "--ignore-scripts",
        f"--registry={NPM_REGISTRY}",
        f"--package={package_tarball}",
        "--",
        "ctx7",
        "login",
        "--no-browser",
    ]
    return [*privileged_prefix(uid, gid), *command]


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


def run_login_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    cancel_stream=None,
) -> None:
    if cancel_stream is None and sys.stdin.isatty():
        cancel_stream = sys.stdin

    if cancel_stream is not None:
        print("Remote Dev cancellation: type q and press Enter while waiting for authorization.")

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            umask=0o077,
        )
    except OSError as exc:
        raise DeviceLoginError(f"could not start the transient Context7 CLI: errno {exc.errno}") from exc

    deadline = time.monotonic() + LOGIN_TIMEOUT_SECONDS
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate_process_group(process)
                raise DeviceLoginError("Context7 device login timed out")
            wait_seconds = min(PROCESS_POLL_SECONDS, remaining)

            if cancel_stream is None:
                time.sleep(wait_seconds)
                continue

            try:
                ready, _, _ = select.select([cancel_stream], [], [], wait_seconds)
            except (OSError, ValueError):
                cancel_stream = None
                continue
            if not ready:
                continue

            line = cancel_stream.readline()
            if line == "":
                cancel_stream = None
                continue
            if line.strip().lower() in {"q", "quit", "c", "cancel"}:
                terminate_process_group(process)
                raise DeviceLoginError("cancelled")
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


def acquire_api_key(*, cli_channel: str) -> tuple[str, str, bool]:
    validate_executable(NPM, label="npm")
    node_version = configured_node_version()
    uid, gid = sandbox_identity()
    login_root = create_login_root(uid, gid)
    package_root: Path | None = None
    environment = transient_environment(login_root, node_version=node_version)
    api_key = ""
    version = ""
    reviewed = False
    try:
        package_root = create_package_root(gid)
        metadata, reviewed = choose_cli_metadata(
            cli_channel,
            uid=uid,
            gid=gid,
            cwd=login_root,
            environment=environment,
        )
        version = metadata["version"]
        package_tarball = download_verified_package(
            metadata,
            root=package_root,
            gid=gid,
            environment=environment,
        )
        if reviewed:
            print(f"Context7 CLI selected: {version} (official npm; reviewed by Remote Dev)")
        else:
            print(
                f"Context7 CLI selected: {version} "
                "(official npm; Remote Dev review pending)",
                file=sys.stderr,
            )
        command = login_command(uid, gid, package_tarball=package_tarball)
        artifact_owner = 0 if os.geteuid() == 0 else os.geteuid()
        validate_package_tarball(
            package_tarball,
            expected_uid=artifact_owner,
            expected_gid=gid,
            expected_integrity=metadata["integrity"],
        )
        run_login_process(command, cwd=login_root, environment=environment)
        api_key = read_credentials(login_root, expected_uid=uid)
    finally:
        if package_root is None:
            remove_login_root(login_root)
        else:
            remove_transient_roots(login_root, package_root)
    return api_key, version, reviewed


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


def command_login(*, yes: bool, cli_channel: str = "auto") -> int:
    confirm(yes=yes)

    # Validate the current ownership/configuration boundary without changing it.
    # A failed or cancelled vendor login must not rewrite config or authentication state.
    preflight_manager_state()

    api_key, version, reviewed = acquire_api_key(cli_channel=cli_channel)

    # The key is transferred only over the child process stdin. It is never a
    # command-line argument, environment variable, log line or temporary TOML value.
    run_manager(["repair", "--yes", "--api-key-stdin"], input_text=api_key + "\n")
    review_text = "reviewed" if reviewed else "review pending"
    print(
        f"Context7 device login: API key adopted into Remote Dev private state "
        f"(ctx7 {version}, {review_text})"
    )
    print("Transient Context7 CLI/login state: removed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="remote-dev-context7-device-login",
        description="Sign in to Context7 through a transient isolated device-code flow.",
    )
    parser.add_argument("--yes", action="store_true")
    parser.add_argument(
        "--cli-channel",
        choices=("auto", "reviewed", "latest"),
        default="auto",
        help="choose the reviewed CLI, current latest official CLI, or interactive auto selection",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        validate_role()
        return command_login(yes=args.yes, cli_channel=args.cli_channel)
    except DeviceLoginError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("ERROR: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
