#!/usr/bin/env python3
"""Manage an optional official Codex runtime with an immutable bundled fallback."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import platform
import re
import select
import shutil
import signal
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(
    os.environ.get(
        "REMOTE_DEV_CODEX_RUNTIME_ROOT",
        "/root/.local/share/remote-dev/codex-runtime",
    )
)
BUNDLED = Path(
    os.environ.get("REMOTE_DEV_CODEX_BUNDLED_BINARY", "/usr/local/bin/codex")
)
LATEST_URL = "https://api.github.com/repos/openai/codex/releases/latest"
SYSTEM_CA_FILE = Path("/etc/ssl/certs/ca-certificates.crt")
ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}
STABLE_RE = re.compile(r"^rust-v([0-9]+\.[0-9]+\.[0-9]+)$")
VERSION_RE = re.compile(r"^codex-cli ([0-9]+\.[0-9]+\.[0-9]+)$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CURRENT_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{16}-[0-9a-f]{8}$")
REQUIRED_FILES = (
    "bin/codex",
    "bin/codex-code-mode-host",
    "codex-path/rg",
    "codex-resources/bwrap",
    "codex-package.json",
)
TOP_LEVEL = {"bin", "codex-path", "codex-resources", "codex-package.json"}
MAX_PACKAGE = 300 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024
MAX_MEMBER = 512 * 1024 * 1024
MAX_MEMBERS = 128
MAX_METADATA = 4 * 1024 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
MAX_POINTER = 256
MAX_STAMP = 256 * 1024
MAX_PROBE_OUTPUT = 1024 * 1024
TIMEOUT = 20
SCHEMA = 1
STAMP_SCHEMA = 1
FINGERPRINT_ALGORITHM = "linux-stat-v1"
MAX_STAMP_OBJECTS = 2048
NOBODY = 65534
STAGING_ROOT = Path("/run/remote-dev-codex-update")


class ManagerError(RuntimeError):
    """A bounded admission or local-integrity check failed."""


class OperationInterrupted(Exception):
    """A catchable signal interrupted transient update work."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


@dataclass(frozen=True)
class RuntimeInspection:
    """One structurally validated optional runtime generation."""

    release_name: str
    version: str
    runtime_target: str
    binary: Path
    manifest_sha256: str
    fingerprints: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class StampRefreshResult:
    refreshed: bool
    stale: bool = False
    error: str | None = None


def fail(message: str) -> NoReturn:
    raise ManagerError(message)


def version_tuple(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        fail(f"invalid semantic version: {value}")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def target() -> str:
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        return "x86_64-unknown-linux-musl"
    if machine in {"aarch64", "arm64"}:
        return "aarch64-unknown-linux-musl"
    fail(f"unsupported Codex runtime architecture: {machine}")


def expected_owner() -> int:
    return os.geteuid()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        fail(f"cannot hash Codex runtime file {path}: {exc}")
    return digest.hexdigest()


def real_file(path: Path, *, executable: bool = False) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"required runtime file is unavailable: {path}: {exc}")
    if not stat.S_ISREG(info.st_mode):
        fail(f"runtime path is not a regular file: {path}")
    if info.st_uid != expected_owner():
        fail(f"runtime file has unexpected owner: {path}")
    if executable and not info.st_mode & stat.S_IXUSR:
        fail(f"runtime executable is not owner-executable: {path}")
    if info.st_mode & 0o022:
        fail(f"runtime file is group/world writable: {path}")
    return info


def real_dir(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"runtime directory is unavailable: {path}: {exc}")
    if not stat.S_ISDIR(info.st_mode):
        fail(f"runtime path is not a real directory: {path}")
    if info.st_uid != expected_owner():
        fail(f"runtime directory has unexpected owner: {path}")
    if info.st_mode & 0o022:
        fail(f"runtime directory is group/world writable: {path}")
    return info


def fingerprint_record(path: Path, label: str) -> dict[str, Any]:
    """Describe one object without following links or reading file contents."""
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"cannot fingerprint Codex runtime object {path}: {exc}")
    if stat.S_ISREG(info.st_mode):
        kind = "file"
    elif stat.S_ISDIR(info.st_mode):
        kind = "directory"
    elif stat.S_ISLNK(info.st_mode):
        fail(f"Codex runtime object is a symlink: {path}")
    else:
        # The current full verifier ignores additional non-file package
        # objects. Record them as a change signal without widening #113 into
        # the stricter object-type admission policy tracked by #114.
        kind = "other"
    return {
        "path": label,
        "kind": kind,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "st_nlink": info.st_nlink,
        "st_size": info.st_size,
        "st_uid": info.st_uid,
        "st_gid": info.st_gid,
        "st_mode": info.st_mode,
        "st_mtime_ns": info.st_mtime_ns,
        "st_ctime_ns": info.st_ctime_ns,
    }


def package_fingerprints(package: Path, *, prefix: str) -> tuple[dict[str, Any], ...]:
    result = [fingerprint_record(package, prefix)]
    try:
        for path in sorted(package.rglob("*")):
            rel = path.relative_to(package).as_posix()
            result.append(fingerprint_record(path, f"{prefix}/{rel}"))
    except OSError as exc:
        fail(f"cannot fingerprint Codex runtime package: {exc}")
    return tuple(result)


def runtime_fingerprints(
    current: Path, release: Path, manifest_path: Path, package: Path, release_name: str
) -> tuple[dict[str, Any], ...]:
    release_label = f"releases/{release_name}"
    result = [
        fingerprint_record(current, "current"),
        fingerprint_record(release, release_label),
        fingerprint_record(manifest_path, f"{release_label}/remote-dev-runtime.json"),
        *package_fingerprints(package, prefix=f"{release_label}/package"),
    ]
    result.sort(key=lambda item: item["path"])
    return tuple(result)


def prepare_root() -> None:
    try:
        if ROOT.exists() or ROOT.is_symlink():
            real_dir(ROOT)
        else:
            ROOT.mkdir(parents=True, mode=0o700)
        ROOT.chmod(0o700)
    except OSError as exc:
        fail(f"cannot prepare Codex runtime root {ROOT}: {exc}")


def prepare_staging_root() -> None:
    """Prepare a fixed executable transient root without exposing runtime state."""
    try:
        real_dir(STAGING_ROOT.parent)
        if STAGING_ROOT.exists() or STAGING_ROOT.is_symlink():
            real_dir(STAGING_ROOT)
        else:
            STAGING_ROOT.mkdir(mode=0o711)
        STAGING_ROOT.chmod(0o711)
    except OSError as exc:
        fail(f"cannot prepare Codex update staging root {STAGING_ROOT}: {exc}")
    probe_staging_execution()


def probe_staging_execution() -> None:
    """Prove the fixed staging filesystem permits bounded unprivileged exec."""
    try:
        with tempfile.TemporaryDirectory(
            prefix=".exec-probe-", dir=STAGING_ROOT
        ) as text:
            probe_dir = Path(text)
            probe_dir.chmod(0o711)
            probe = probe_dir / "probe"
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            flags |= getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(probe, flags, 0o700)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    descriptor = -1
                    output.write(b"#!/bin/sh\nexit 0\n")
                    output.flush()
                    os.fchmod(output.fileno(), 0o755)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            require_candidate_path(probe, executable=True)
            try:
                result = subprocess.run(
                    [str(probe)],
                    cwd="/",
                    env={"PATH": "/usr/bin:/bin"},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                    **candidate_identity_kwargs(),
                )
            except subprocess.TimeoutExpired:
                fail("Codex update staging execution probe timed out")
            except OSError as exc:
                fail(
                    "Codex update staging root does not permit candidate "
                    f"execution: {exc}"
                )
            if result.returncode != 0:
                fail(
                    "Codex update staging root failed its candidate execution "
                    f"probe with status {result.returncode}"
                )
    except ManagerError:
        raise
    except OSError as exc:
        fail(f"cannot probe Codex update staging root execution: {exc}")


@contextlib.contextmanager
def update_staging() -> Iterator[Path]:
    """Create one fixed-location staging tree and clean it on every normal exit."""
    previous_handlers: dict[signal.Signals, Any] = {}

    def interrupted(signum: int, _frame: object) -> NoReturn:
        raise OperationInterrupted(signum)

    try:
        for signame in ("SIGHUP", "SIGTERM"):
            signum = getattr(signal, signame, None)
            if signum is not None:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupted)
        prepare_staging_root()
        with tempfile.TemporaryDirectory(
            prefix="update-", dir=STAGING_ROOT
        ) as text:
            staging = Path(text)
            # The package is root-owned but must remain traversable after the
            # candidate process drops to the fixed unprivileged identity.
            staging.chmod(0o711)
            yield staging
    finally:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


@contextlib.contextmanager
def runtime_lock() -> Iterator[None]:
    """Serialize mutations while keeping launch/status lock-free."""
    prepare_root()
    lock_path = ROOT / ".lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        fail(f"cannot open Codex runtime mutation lock: {exc}")
    try:
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_owner():
                fail("Codex runtime mutation lock has invalid identity")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            fail(f"cannot secure Codex runtime mutation lock: {exc}")
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def bundled_version() -> str:
    real_file(BUNDLED, executable=True)
    try:
        result = subprocess.run(
            [str(BUNDLED), "--version"],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"cannot determine bundled Codex version: {exc}")
    match = VERSION_RE.fullmatch(result.stdout.strip())
    if not match:
        fail(f"unexpected bundled Codex version output: {result.stdout.strip()!r}")
    return match.group(1)


def validate_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or host not in ALLOWED_HOSTS
        or parsed.port not in (None, 443)
    ):
        fail(f"refusing unexpected Codex runtime URL: {url}")
    if parsed.username is not None or parsed.password is not None:
        fail("refusing authenticated Codex runtime URL")


class Redirects(urllib.request.HTTPRedirectHandler):
    """Permit redirects only while every URL remains on reviewed HTTPS origins."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def ssl_context() -> ssl.SSLContext:
    if not SYSTEM_CA_FILE.is_file():
        fail(f"system CA bundle is unavailable: {SYSTEM_CA_FILE}")
    context = ssl.create_default_context(cafile=str(SYSTEM_CA_FILE))
    extra_ca = os.environ.get("CODEX_CA_CERTIFICATE", "").strip()
    if extra_ca:
        ca_path = Path(extra_ca)
        try:
            info = ca_path.lstat()
        except OSError as exc:
            fail(f"CODEX_CA_CERTIFICATE is unavailable: {exc}")
        if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > MAX_METADATA:
            fail("CODEX_CA_CERTIFICATE must be a bounded regular file")
        try:
            context.load_verify_locations(cafile=str(ca_path))
        except (OSError, ssl.SSLError) as exc:
            fail(f"cannot load CODEX_CA_CERTIFICATE: {exc}")
    return context


def opener() -> urllib.request.OpenerDirector:
    # Default ProxyHandler behavior intentionally honors HTTP(S)_PROXY/NO_PROXY,
    # matching the existing Codex deployment contract. URL validation still
    # constrains request, redirect and final destination origins.
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(),
        urllib.request.HTTPSHandler(context=ssl_context()),
        Redirects(),
    )


def latest_asset() -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_URL,
        headers={
            "User-Agent": "remote-dev-containers-codex-runtime",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with opener().open(request, timeout=TIMEOUT) as response:
            validate_url(response.geturl())
            payload = response.read(MAX_METADATA + 1)
    except (
        OSError,
        http.client.HTTPException,
        urllib.error.URLError,
        urllib.error.HTTPError,
    ) as exc:
        fail(f"cannot fetch official Codex release metadata: {exc}")
    if len(payload) > MAX_METADATA:
        fail("official Codex release metadata exceeds size limit")
    try:
        metadata = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"official Codex release metadata is invalid JSON: {exc}")
    if not isinstance(metadata, dict):
        fail("official Codex release metadata is not an object")
    tag = metadata.get("tag_name")
    match = STABLE_RE.fullmatch(tag or "") if isinstance(tag, str) else None
    if not match:
        fail(f"latest official Codex release is not an exact stable tag: {tag!r}")
    version = match.group(1)
    package_target = target()
    name = f"codex-package-{package_target}.tar.gz"
    assets = metadata.get("assets")
    found = (
        [item for item in assets if isinstance(item, dict) and item.get("name") == name]
        if isinstance(assets, list)
        else []
    )
    if len(found) != 1:
        fail(f"official release must contain exactly one {name} asset")
    item = found[0]
    url = item.get("browser_download_url")
    digest = item.get("digest")
    size = item.get("size")
    if not isinstance(url, str):
        fail(f"official asset {name} has no URL")
    validate_url(url)
    if (
        not isinstance(digest, str)
        or not digest.startswith("sha256:")
        or not SHA_RE.fullmatch(digest[7:])
    ):
        fail(f"official asset {name} has no valid GitHub SHA-256 digest")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_PACKAGE:
        fail(f"official asset {name} has invalid/excessive size")
    return {
        "tag": tag,
        "version": version,
        "target": package_target,
        "name": name,
        "url": url,
        "sha256": digest[7:],
        "size": size,
    }


def download(asset: dict[str, Any], destination: Path) -> str:
    request = urllib.request.Request(
        asset["url"], headers={"User-Agent": "remote-dev-containers-codex-runtime"}
    )
    digest = hashlib.sha256()
    size = 0
    try:
        with opener().open(request, timeout=TIMEOUT) as response, destination.open(
            "xb"
        ) as output:
            final_url = response.geturl()
            validate_url(final_url)
            advertised = response.headers.get("Content-Length")
            if advertised is not None and int(advertised) != asset["size"]:
                fail("official package Content-Length differs from release metadata")
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > asset["size"] or size > MAX_PACKAGE:
                    fail("official package exceeded its declared size")
                output.write(chunk)
                digest.update(chunk)
    except ManagerError:
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    except (
        OSError,
        ValueError,
        http.client.HTTPException,
        urllib.error.URLError,
        urllib.error.HTTPError,
    ) as exc:
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        fail(f"cannot download official Codex runtime package: {exc}")
    if size != asset["size"] or digest.hexdigest() != asset["sha256"]:
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        fail("official Codex package size or SHA-256 does not match release metadata")
    return final_url


def member_path(name: str) -> Path:
    path = Path(name)
    if not name or "\x00" in name or path.is_absolute() or ".." in path.parts:
        fail(f"unsafe Codex package member: {name!r}")
    if not path.parts or path.parts[0] not in TOP_LEVEL:
        fail(f"unexpected Codex package member: {name!r}")
    return path


def prepare_extracted_directory(destination: Path, directory: Path) -> None:
    """Create and normalize every candidate directory independently of umask."""
    directory.mkdir(parents=True, exist_ok=True)
    current = destination
    current.chmod(0o755)
    for part in directory.relative_to(destination).parts:
        current = current / part
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode):
            fail(f"Codex package path is not a directory: {current}")
        current.chmod(0o755)


def extract(archive_path: Path, destination: Path) -> None:
    try:
        prepare_extracted_directory(destination, destination)
        with tarfile.open(archive_path, "r:gz") as archive:
            members = archive.getmembers()
            if not 1 <= len(members) <= MAX_MEMBERS:
                fail(f"unexpected Codex package member count: {len(members)}")
            seen: set[str] = set()
            total = 0
            for member in members:
                rel = member_path(member.name).as_posix()
                if rel in seen:
                    fail(f"duplicate Codex package member: {rel}")
                seen.add(rel)
                if (
                    member.issym()
                    or member.islnk()
                    or member.isdev()
                    or member.isfifo()
                    or not (member.isdir() or member.isfile())
                ):
                    fail(f"unsupported Codex package member type: {rel}")
                if member.size < 0 or member.size > MAX_MEMBER:
                    fail(f"invalid/excessive Codex package member size: {rel}")
                total += member.size if member.isfile() else 0
                if total > MAX_UNPACKED:
                    fail("Codex package exceeds unpacked size limit")
            for member in members:
                rel = member_path(member.name)
                output = destination.joinpath(*rel.parts)
                if member.isdir():
                    prepare_extracted_directory(destination, output)
                    continue
                prepare_extracted_directory(destination, output.parent)
                source = archive.extractfile(member)
                if source is None:
                    fail(f"cannot read Codex package member: {rel}")
                with source, output.open("xb") as target_file:
                    shutil.copyfileobj(source, target_file, 1024 * 1024)
                output.chmod(0o755 if member.mode & 0o111 else 0o644)
    except ManagerError:
        raise
    except (OSError, tarfile.TarError) as exc:
        fail(f"cannot inspect/extract official Codex package: {exc}")


def package_metadata(
    package: Path, expected: dict[str, Any] | None = None
) -> dict[str, Any]:
    for rel in REQUIRED_FILES:
        real_file(package / rel, executable=rel != "codex-package.json")
    metadata_path = package / "codex-package.json"
    metadata_info = real_file(metadata_path)
    if metadata_info.st_size > MAX_METADATA:
        fail("Codex package metadata exceeds size limit")
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"invalid Codex package metadata: {exc}")
    if not isinstance(data, dict):
        fail("Codex package metadata is not an object")
    wanted = {
        "layoutVersion": 1,
        "target": (expected or {}).get("target", target()),
        "variant": "codex",
        "entrypoint": "bin/codex",
        "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    for key, value in wanted.items():
        if data.get(key) != value:
            fail(f"Codex package metadata {key!r} mismatch")
    version = data.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", version
    ):
        fail("Codex package metadata has invalid version")
    if expected and version != expected["version"]:
        fail(f"Codex package version mismatch: {version} != {expected['version']}")
    return data


def candidate_identity_kwargs() -> dict[str, Any]:
    if os.name != "posix" or os.geteuid() != 0:
        return {}
    return {"user": NOBODY, "group": NOBODY, "extra_groups": []}


def candidate_identity() -> tuple[int, int]:
    if os.geteuid() == 0:
        return NOBODY, NOBODY
    return os.geteuid(), os.getegid()


def identity_has_mode(info: os.stat_result, uid: int, gid: int, mode: int) -> bool:
    if uid == info.st_uid:
        required = mode << 6
    elif gid == info.st_gid:
        required = mode << 3
    else:
        required = mode
    return info.st_mode & required == required


def require_candidate_path(path: Path, *, executable: bool = False) -> None:
    """Prove the dropped candidate identity can traverse and use a fixed path."""
    if not path.is_absolute():
        fail(f"candidate path is not absolute: {path}")
    uid, gid = candidate_identity()
    for parent in reversed(path.parents):
        try:
            info = parent.lstat()
        except OSError as exc:
            fail(f"candidate path parent is unavailable: {parent}: {exc}")
        if not stat.S_ISDIR(info.st_mode) or not identity_has_mode(
            info, uid, gid, stat.S_IXOTH
        ):
            fail(
                "candidate path parent is not traversable by the probe identity: "
                f"{parent}"
            )
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"candidate path is unavailable: {path}: {exc}")
    required = stat.S_IXOTH if executable or stat.S_ISDIR(info.st_mode) else stat.S_IROTH
    if executable and not stat.S_ISREG(info.st_mode):
        fail(f"candidate executable is not a regular file: {path}")
    if not identity_has_mode(info, uid, gid, required):
        fail(f"candidate path is inaccessible to the probe identity: {path}")


def prepare_candidate_directories(staging: Path) -> tuple[Path, Path]:
    home = staging / "probe-home"
    cwd = staging / "probe-cwd"
    try:
        home.mkdir(mode=0o700)
        cwd.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(home, NOBODY, NOBODY)
            os.chown(cwd, NOBODY, NOBODY)
        home.chmod(0o700)
        cwd.chmod(0o700)
    except OSError as exc:
        fail(f"cannot prepare synthetic candidate state: {exc}")
    require_candidate_path(home)
    require_candidate_path(cwd)
    return home, cwd


def candidate_env(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "CODEX_HOME": str(home / ".codex"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "DO_NOT_TRACK": "1",
    }


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def candidate_run(
    argv: list[str], cwd: Path, home: Path, *, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    """Run fixed candidate commands with bounded time/output and synthetic state."""
    require_candidate_path(Path(argv[0]), executable=True)
    require_candidate_path(cwd)
    require_candidate_path(home)
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=candidate_env(home),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            **candidate_identity_kwargs(),
        )
    except OSError as exc:
        fail(f"cannot execute candidate Codex probe: {exc}")
    if process.stdout is None or process.stderr is None:
        terminate(process)
        fail("candidate output pipes are unavailable")
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    open_streams = set(output)
    deadline = time.monotonic() + timeout
    try:
        while open_streams:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                terminate(process)
                fail(f"candidate command timed out: {argv[0]}")
            ready, _, _ = select.select(
                list(open_streams), [], [], min(0.1, remaining)
            )
            for stream in ready:
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    open_streams.remove(stream)
                    continue
                output[stream].extend(chunk)
                if sum(len(value) for value in output.values()) > MAX_PROBE_OUTPUT:
                    terminate(process)
                    fail(f"candidate command exceeded output limit: {argv[0]}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            terminate(process)
            fail(f"candidate command timed out: {argv[0]}")
        returncode = process.wait(timeout=remaining)
    except subprocess.TimeoutExpired:
        terminate(process)
        fail(f"candidate command timed out: {argv[0]}")
    finally:
        if process.poll() is None:
            terminate(process)
        process.stdout.close()
        process.stderr.close()
    return subprocess.CompletedProcess(
        argv,
        returncode,
        bytes(output[process.stdout]).decode("utf-8", errors="replace"),
        bytes(output[process.stderr]).decode("utf-8", errors="replace"),
    )


def probe_host(host: Path, cwd: Path, home: Path) -> None:
    require_candidate_path(host, executable=True)
    require_candidate_path(cwd)
    require_candidate_path(home)
    try:
        process = subprocess.Popen(
            [str(host), "--listen", "ws://127.0.0.1:0"],
            cwd=cwd,
            env=candidate_env(home),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            **candidate_identity_kwargs(),
        )
    except OSError as exc:
        fail(f"cannot execute candidate code-mode host probe: {exc}")
    if process.stdout is None or process.stderr is None:
        terminate(process)
        fail("candidate code-mode host output pipes are unavailable")
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + 5

    def drain(wait: float) -> None:
        ready, _, _ = select.select(
            [process.stdout, process.stderr], [], [], max(0.0, wait)
        )
        for stream in ready:
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                continue
            (stdout if stream is process.stdout else stderr).extend(chunk)
            if len(stdout) + len(stderr) > MAX_PROBE_OUTPUT:
                fail("candidate code-mode host exceeded output limit")

    try:
        while b"\n" not in stdout:
            if process.poll() is not None:
                fail(
                    "candidate code-mode host exited before publishing readiness: "
                    + stderr.decode("utf-8", errors="replace")[-4096:]
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                fail("candidate code-mode host timed out before publishing readiness")
            drain(min(0.1, remaining))
        first_line = bytes(stdout).split(b"\n", 1)[0].decode(
            "utf-8", errors="replace"
        )
        match = re.fullmatch(r"ws://127\.0\.0\.1:([0-9]{1,5})", first_line)
        if not match or not 1 <= int(match.group(1)) <= 65535:
            fail(f"candidate code-mode host published unexpected URL: {first_line!r}")
        port = int(match.group(1))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                fail(
                    "candidate code-mode host exited before readiness: "
                    + stderr.decode("utf-8", errors="replace")[-4096:]
                )
            drain(0)
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            try:
                connection.request("GET", "/readyz")
                response = connection.getresponse()
                response.read()
                if response.status == 200:
                    return
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()
            time.sleep(0.05)
        fail("candidate code-mode host did not become ready")
    finally:
        terminate(process)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def validate_candidate(
    package: Path, expected_version: str, *, home: Path, cwd: Path
) -> None:
    result = candidate_run([str(package / "bin/codex"), "--version"], cwd, home)
    match = VERSION_RE.fullmatch(result.stdout.strip()) if result.returncode == 0 else None
    if not match or match.group(1) != expected_version:
        fail("candidate Codex version probe failed")
    help_result = candidate_run([str(package / "bin/codex"), "--help"], cwd, home)
    if help_result.returncode != 0 or any(
        flag not in help_result.stdout for flag in ("--sandbox", "--ask-for-approval")
    ):
        fail("candidate Codex launcher compatibility probe failed")
    probe_host(package / "bin/codex-code-mode-host", cwd, home)


def records(package: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        for path in sorted(package.rglob("*")):
            if path.is_symlink():
                fail(f"candidate package contains a symlink: {path}")
            if path.is_dir():
                continue
            rel = path.relative_to(package).as_posix()
            info = real_file(path)
            result.append(
                {
                    "path": rel,
                    "size": info.st_size,
                    "sha256": file_sha(path),
                    "executable": bool(info.st_mode & stat.S_IXUSR),
                }
            )
    except OSError as exc:
        fail(f"cannot inspect Codex package files: {exc}")
    return result


def read_previous_name() -> str | None:
    current = ROOT / "current"
    if not current.exists() and not current.is_symlink():
        return None
    try:
        info = real_file(current)
        if info.st_size > MAX_POINTER:
            return None
        name = current.read_text(encoding="utf-8").strip()
    except (ManagerError, OSError, UnicodeDecodeError):
        return None
    return name if CURRENT_RE.fullmatch(name) else None


def prepare_releases() -> Path:
    releases = ROOT / "releases"
    if releases.exists() or releases.is_symlink():
        real_dir(releases)
    else:
        releases.mkdir(mode=0o700)
    releases.chmod(0o700)
    return releases


def discard_path(path: Path) -> Path:
    discarded = path.parent / f".discard-{uuid.uuid4().hex}"
    os.replace(path, discarded)
    return discarded


def stage_abandoned_candidates(releases: Path) -> list[Path]:
    """Atomically detach inactive candidate trees for lock-free deletion."""
    discarded: list[Path] = []
    for old in releases.iterdir():
        if old.name.startswith(".discard-"):
            discarded.append(old)
            continue
        if (
            not old.name.startswith(".candidate-")
            or not old.is_dir()
            or old.is_symlink()
        ):
            continue
        marker = old / ".in-use"
        descriptor = -1
        try:
            flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(marker, flags)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_owner():
                discarded.append(discard_path(old))
                continue
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            discarded.append(discard_path(old))
        except FileNotFoundError:
            # Legacy or interrupted candidates have no marker file at all.
            if old.exists() and not old.is_symlink():
                discarded.append(discard_path(old))
        except OSError:
            # Keep candidates whose marker identity cannot be evaluated now.
            continue
        finally:
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
    return discarded


def remove_discarded(paths: list[Path]) -> None:
    for path in paths:
        if path.exists() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)


def initialize_verification_stamp(
    release_name: str,
    manifest_bytes: bytes,
    candidate_package_fingerprints: tuple[dict[str, Any], ...],
) -> None:
    """Best-effort stamp initialization for an already published generation."""
    try:
        final_inspection = inspect_active_runtime(full_hash=False)
        final_package = ROOT / "releases" / release_name / "package"
        final_matches = (
            final_inspection is not None
            and final_inspection.release_name == release_name
            and final_inspection.manifest_sha256
            == hashlib.sha256(manifest_bytes).hexdigest()
            and package_fingerprints(final_package, prefix="package")
            == candidate_package_fingerprints
        )
    except ManagerError as exc:
        final_matches = False
        final_inspection = None
        stamp_warning = str(exc)
    else:
        stamp_warning = "active generation changed"
    if not final_matches or final_inspection is None:
        print(
            "WARNING: Codex runtime was published after full verification, "
            "but its verification stamp was not initialized: "
            f"{stamp_warning}.",
            file=sys.stderr,
        )
        return
    refreshed = refresh_verification_stamp(final_inspection)
    if not refreshed.refreshed:
        print(
            "WARNING: Codex runtime was published after full verification, "
            "but its verification stamp could not be initialized: "
            f"{refreshed.error or 'runtime generation changed'}",
            file=sys.stderr,
        )


def publish(package: Path, asset: dict[str, Any], final_url: str) -> None:
    expected_records = records(package)
    release_name = (
        f"{asset['version']}-{asset['sha256'][:16]}-{uuid.uuid4().hex[:8]}"
    )
    staging: Path | None = None
    marker_descriptor = -1
    published = False
    discarded: list[Path] = []
    candidate_package_fingerprints: tuple[dict[str, Any], ...] | None = None
    try:
        with runtime_lock():
            releases = prepare_releases()
            discarded.extend(stage_abandoned_candidates(releases))
            staging = releases / f".candidate-{uuid.uuid4().hex}"
            staging.mkdir(mode=0o700)
            marker = staging / ".in-use"
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            marker_descriptor = os.open(marker, flags, 0o600)
            os.fchmod(marker_descriptor, 0o600)
            fcntl.flock(marker_descriptor, fcntl.LOCK_EX)
        remove_discarded(discarded)
        discarded.clear()

        destination = staging / "package"
        shutil.copytree(package, destination)
        for path in [destination, *destination.rglob("*")]:
            if path.is_symlink():
                fail("published Codex runtime cannot contain symlinks")
            if path.is_dir():
                path.chmod(0o700)
            elif path.is_file():
                path.chmod(0o700 if path.stat().st_mode & stat.S_IXUSR else 0o600)
        before_hash = package_fingerprints(destination, prefix="package")
        if records(destination) != expected_records:
            fail("candidate Codex package changed while publishing")
        candidate_package_fingerprints = package_fingerprints(
            destination, prefix="package"
        )
        if before_hash != candidate_package_fingerprints:
            fail("candidate Codex package changed while publishing")

        manifest = {
            "schema_version": SCHEMA,
            "version": asset["version"],
            "release_tag": asset["tag"],
            "target": asset["target"],
            "source_url": asset["url"],
            "final_url": final_url,
            "package_name": asset["name"],
            "package_sha256": asset["sha256"],
            "package_size": asset["size"],
            "files": expected_records,
            "installed_at": int(time.time()),
        }
        manifest_path = staging / "remote-dev-runtime.json"
        manifest_bytes = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode()
        manifest_path.write_bytes(manifest_bytes)
        manifest_path.chmod(0o600)
        candidate_manifest_fingerprint = fingerprint_record(manifest_path, "manifest")

        with runtime_lock():
            releases = prepare_releases()
            if staging.parent != releases or not staging.exists():
                fail("candidate Codex package disappeared while publishing")
            if (
                package_fingerprints(destination, prefix="package")
                != candidate_package_fingerprints
                or fingerprint_record(manifest_path, "manifest")
                != candidate_manifest_fingerprint
            ):
                fail("candidate Codex package changed while publishing")
            previous_name = read_previous_name()
            final_release = releases / release_name
            marker.unlink()
            os.replace(staging, final_release)
            pointer = ROOT / f".current-{uuid.uuid4().hex}"
            pointer.write_text(release_name + "\n", encoding="utf-8")
            pointer.chmod(0o600)
            os.replace(pointer, ROOT / "current")
            published = True
            keep_names = {release_name}
            if previous_name:
                keep_names.add(previous_name)
            discarded.extend(stage_abandoned_candidates(releases))
            for old in releases.iterdir():
                if (
                    old.name not in keep_names
                    and old.is_dir()
                    and not old.is_symlink()
                    and not old.name.startswith((".candidate-", ".discard-"))
                ):
                    discarded.append(discard_path(old))
        remove_discarded(discarded)
        discarded.clear()

        initialize_verification_stamp(
            release_name, manifest_bytes, candidate_package_fingerprints
        )
    except ManagerError:
        raise
    except OSError as exc:
        fail(f"cannot publish Codex runtime: {exc}")
    finally:
        if marker_descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(marker_descriptor)
        remove_discarded(discarded)
        if (
            not published
            and staging is not None
            and staging.exists()
            and not staging.is_symlink()
        ):
            shutil.rmtree(staging, ignore_errors=True)


def validate_manifest(manifest: object) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA:
        fail("Codex runtime manifest is incompatible")
    version = manifest.get("version")
    release_tag = manifest.get("release_tag")
    manifest_target = manifest.get("target")
    source_url = manifest.get("source_url")
    final_url = manifest.get("final_url")
    package_sha = manifest.get("package_sha256")
    package_size = manifest.get("package_size")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+", version
    ):
        fail("Codex runtime manifest has invalid version")
    if release_tag != f"rust-v{version}":
        fail("Codex runtime manifest has inconsistent release tag")
    if manifest_target != target():
        fail("Codex runtime manifest target is incompatible")
    if not isinstance(source_url, str) or not isinstance(final_url, str):
        fail("Codex runtime manifest has invalid source URL")
    validate_url(source_url)
    validate_url(final_url)
    if not isinstance(package_sha, str) or not SHA_RE.fullmatch(package_sha):
        fail("Codex runtime manifest has invalid package digest")
    if (
        not isinstance(package_size, int)
        or isinstance(package_size, bool)
        or not 1 <= package_size <= MAX_PACKAGE
    ):
        fail("Codex runtime manifest has invalid package size")
    return manifest


def verify_package_files(
    package: Path, manifest: dict[str, Any], *, full_hash: bool = True
) -> set[str]:
    """Apply the shared package rules, optionally adding full content hashes."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files or len(files) > MAX_MEMBERS:
        fail("Codex runtime manifest has invalid file records")
    expected_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or set(item) != {
            "path",
            "size",
            "sha256",
            "executable",
        }:
            fail("Codex runtime manifest has malformed file record")
        rel_value = item.get("path")
        size = item.get("size")
        sha = item.get("sha256")
        executable = item.get("executable")
        if not isinstance(rel_value, str):
            fail("Codex runtime manifest has malformed file path")
        rel = member_path(rel_value)
        if rel.as_posix() != rel_value or rel_value in expected_paths:
            fail("Codex runtime manifest has invalid/duplicate file path")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or size > MAX_MEMBER
            or not isinstance(sha, str)
            or not SHA_RE.fullmatch(sha)
            or not isinstance(executable, bool)
        ):
            fail("Codex runtime manifest has malformed file identity")
        expected_paths.add(rel_value)
        path = package.joinpath(*rel.parts)
        info = real_file(path, executable=executable)
        if info.st_size != size:
            fail(f"Codex runtime file changed: {rel_value}")
        if full_hash and file_sha(path) != sha:
            fail(f"Codex runtime file changed: {rel_value}")

    actual_paths: set[str] = set()
    try:
        for path in package.rglob("*"):
            if path.is_symlink():
                fail("Codex runtime package file set changed")
            if path.is_file():
                actual_paths.add(path.relative_to(package).as_posix())
    except OSError as exc:
        fail(f"cannot inspect Codex runtime package file set: {exc}")
    if actual_paths != expected_paths:
        fail("Codex runtime package file set changed")
    return expected_paths


def inspect_active_runtime(*, full_hash: bool) -> RuntimeInspection | None:
    current = ROOT / "current"
    if not current.exists() and not current.is_symlink():
        return None
    current_info = real_file(current)
    if current_info.st_size > MAX_POINTER:
        fail("Codex runtime current pointer exceeds size limit")
    try:
        name = current.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        fail(f"Codex runtime current pointer cannot be read: {exc}")
    if not CURRENT_RE.fullmatch(name):
        fail("Codex runtime current pointer is malformed")
    release = ROOT / "releases" / name
    real_dir(release)
    manifest_path = release / "remote-dev-runtime.json"
    manifest_info = real_file(manifest_path)
    if manifest_info.st_size > MAX_MANIFEST:
        fail("Codex runtime manifest exceeds size limit")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = validate_manifest(json.loads(manifest_bytes))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"Codex runtime manifest is invalid: {exc}")
    package = release / "package"
    real_dir(package)
    before = runtime_fingerprints(current, release, manifest_path, package, name)
    verify_package_files(package, manifest, full_hash=full_hash)
    version = manifest["version"]
    if full_hash:
        metadata = package_metadata(package)
        if metadata.get("version") != version:
            fail("Codex runtime version differs between package and private manifest")
    after = runtime_fingerprints(current, release, manifest_path, package, name)
    if before != after:
        fail("Codex runtime changed during integrity inspection")
    return RuntimeInspection(
        release_name=name,
        version=version,
        runtime_target=manifest["target"],
        binary=package / "bin/codex",
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        fingerprints=after,
    )


def stamp_path() -> Path:
    return ROOT / "verification-stamp.json"


def stamp_payload(inspection: RuntimeInspection) -> dict[str, Any]:
    return {
        "schema_version": STAMP_SCHEMA,
        "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "release_name": inspection.release_name,
        "runtime_version": inspection.version,
        "target": inspection.runtime_target,
        "manifest_sha256": inspection.manifest_sha256,
        "fingerprints": list(inspection.fingerprints),
        "verified_at": int(time.time()),
    }


def valid_stamp_fingerprint(item: object) -> bool:
    keys = {
        "path",
        "kind",
        "st_dev",
        "st_ino",
        "st_nlink",
        "st_size",
        "st_uid",
        "st_gid",
        "st_mode",
        "st_mtime_ns",
        "st_ctime_ns",
    }
    if not isinstance(item, dict) or set(item) != keys:
        return False
    label = item.get("path")
    if (
        not isinstance(label, str)
        or not 1 <= len(label) <= 1024
        or "\x00" in label
        or label.startswith("/")
        or ".." in Path(label).parts
    ):
        return False
    if item.get("kind") not in {"file", "directory", "other"}:
        return False
    for key in keys - {"path", "kind"}:
        value = item.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return False
    return True


def read_verification_stamp() -> dict[str, Any] | None:
    path = stamp_path()
    if not path.exists() and not path.is_symlink():
        return None
    try:
        info = real_file(path)
        if not 1 <= info.st_size <= MAX_STAMP:
            return None
        with path.open("rb") as stream:
            payload = stream.read(MAX_STAMP + 1)
        if len(payload) != info.st_size or len(payload) > MAX_STAMP:
            return None
        data = json.loads(payload)
    except (ManagerError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    keys = {
        "schema_version",
        "fingerprint_algorithm",
        "release_name",
        "runtime_version",
        "target",
        "manifest_sha256",
        "fingerprints",
        "verified_at",
    }
    if not isinstance(data, dict) or set(data) != keys:
        return None
    if (
        data.get("schema_version") != STAMP_SCHEMA
        or data.get("fingerprint_algorithm") != FINGERPRINT_ALGORITHM
        or not isinstance(data.get("release_name"), str)
        or not CURRENT_RE.fullmatch(data["release_name"])
        or not isinstance(data.get("runtime_version"), str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", data["runtime_version"])
        or not isinstance(data.get("target"), str)
        or not isinstance(data.get("manifest_sha256"), str)
        or not SHA_RE.fullmatch(data["manifest_sha256"])
    ):
        return None
    verified_at = data.get("verified_at")
    if (
        not isinstance(verified_at, int)
        or isinstance(verified_at, bool)
        or verified_at < 0
    ):
        return None
    fingerprints = data.get("fingerprints")
    if (
        not isinstance(fingerprints, list)
        or not 1 <= len(fingerprints) <= MAX_STAMP_OBJECTS
        or not all(valid_stamp_fingerprint(item) for item in fingerprints)
    ):
        return None
    labels = [item["path"] for item in fingerprints]
    if labels != sorted(labels) or len(labels) != len(set(labels)):
        return None
    return data


def stamp_matches(inspection: RuntimeInspection) -> bool:
    stamp = read_verification_stamp()
    if stamp is None:
        return False
    return (
        stamp["release_name"] == inspection.release_name
        and stamp["runtime_version"] == inspection.version
        and stamp["target"] == inspection.runtime_target
        and stamp["manifest_sha256"] == inspection.manifest_sha256
        and stamp["fingerprints"] == list(inspection.fingerprints)
    )


def write_verification_stamp(inspection: RuntimeInspection) -> None:
    destination = stamp_path()
    temporary = ROOT / f".verification-stamp-{uuid.uuid4().hex}"
    fingerprints = list(inspection.fingerprints)
    labels = [item["path"] for item in fingerprints]
    if (
        not 1 <= len(fingerprints) <= MAX_STAMP_OBJECTS
        or not all(valid_stamp_fingerprint(item) for item in fingerprints)
        or labels != sorted(labels)
        or len(labels) != len(set(labels))
    ):
        fail("Codex runtime verification fingerprint cannot be persisted safely")
    payload = (
        json.dumps(stamp_payload(inspection), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    if len(payload) > MAX_STAMP:
        fail("Codex runtime verification stamp exceeds size limit")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            descriptor = -1
            output.write(payload)
            output.flush()
            os.fchmod(output.fileno(), 0o600)
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        directory_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        directory_flags |= getattr(os, "O_DIRECTORY", 0)
        directory = os.open(ROOT, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        fail(f"cannot persist Codex runtime verification stamp: {exc}")
    finally:
        if descriptor >= 0:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with contextlib.suppress(OSError):
            temporary.unlink(missing_ok=True)


def same_inspection(left: RuntimeInspection, right: RuntimeInspection) -> bool:
    return (
        left.release_name == right.release_name
        and left.version == right.version
        and left.runtime_target == right.runtime_target
        and left.manifest_sha256 == right.manifest_sha256
        and left.fingerprints == right.fingerprints
    )


def refresh_verification_stamp(
    inspection: RuntimeInspection,
) -> StampRefreshResult:
    try:
        with runtime_lock():
            try:
                current = inspect_active_runtime(full_hash=False)
            except ManagerError as exc:
                return StampRefreshResult(
                    False,
                    stale=True,
                    error=f"runtime changed before stamp publication: {exc}",
                )
            if current is None or not same_inspection(current, inspection):
                return StampRefreshResult(
                    False,
                    stale=True,
                    error="runtime generation changed before stamp publication",
                )
            write_verification_stamp(inspection)
    except ManagerError as exc:
        return StampRefreshResult(False, error=str(exc))
    return StampRefreshResult(True)


def active_runtime(
    *,
    force_full: bool = False,
    require_stamp: bool = False,
    warnings: list[str] | None = None,
) -> tuple[str, Path] | None:
    for attempt in range(2):
        inspection = inspect_active_runtime(full_hash=force_full)
        if inspection is None:
            return None
        if not force_full and stamp_matches(inspection):
            return inspection.version, inspection.binary
        if not force_full:
            inspection = inspect_active_runtime(full_hash=True)
            if inspection is None:
                return None
        refreshed = refresh_verification_stamp(inspection)
        if refreshed.refreshed:
            return inspection.version, inspection.binary
        if refreshed.stale and attempt == 0:
            continue
        message = refreshed.error or "verification stamp could not be refreshed"
        if require_stamp:
            fail(message)
        if warnings is not None:
            warnings.append(message)
        return inspection.version, inspection.binary
    fail("Codex runtime changed repeatedly during verification")


def verify_runtime() -> None:
    try:
        if not ROOT.exists() and not ROOT.is_symlink():
            print(
                "Codex runtime full integrity: OK "
                "(bundled-only; optional runtime not installed)"
            )
            return
        real_dir(ROOT)
        runtime = active_runtime(force_full=True, require_stamp=True)
        if runtime is None:
            print(
                "Codex runtime full integrity: OK "
                "(bundled-only; optional runtime not installed)"
            )
            return
        print(f"Codex runtime full integrity: OK (runtime {runtime[0]})")
    except ManagerError as exc:
        fail(f"Codex runtime full integrity: FAILED: {exc}")


def state() -> dict[str, Any]:
    bundled = bundled_version()
    if not ROOT.exists() and not ROOT.is_symlink():
        return {"kind": "bundled", "bundled": bundled}
    try:
        real_dir(ROOT)
        verification_warnings: list[str] = []
        runtime = active_runtime(warnings=verification_warnings)
    except ManagerError as exc:
        return {"kind": "damaged", "bundled": bundled, "warning": str(exc)}
    if runtime is None:
        return {"kind": "bundled", "bundled": bundled}
    runtime_version, binary = runtime
    if version_tuple(runtime_version) <= version_tuple(bundled):
        result = {
            "kind": "bundled-preferred",
            "bundled": bundled,
            "runtime": runtime_version,
            "binary": binary,
        }
    else:
        result = {
            "kind": "runtime",
            "bundled": bundled,
            "runtime": runtime_version,
            "binary": binary,
        }
    if verification_warnings:
        result["verification_warning"] = verification_warnings[-1]
    return result


def print_status(current: dict[str, Any], *, menu: bool) -> None:
    kind = current["kind"]
    bundled = current["bundled"]
    if menu:
        if kind == "runtime":
            print(
                f"Codex runtime: {current['runtime']} "
                "(official source; review pending)"
            )
        elif kind == "damaged":
            print("Codex runtime: damaged or locally modified (bundled fallback active)")
        elif kind == "bundled-preferred":
            print(
                f"Codex runtime: {current['runtime']} installed "
                f"(bundled {bundled} active)"
            )
        else:
            print(f"Codex: bundled {bundled}")
        return
    print(f"Codex bundled: {bundled}")
    if kind == "runtime":
        print(
            f"Codex runtime: {current['runtime']} "
            "(official source; Remote Dev review pending)"
        )
        print("Codex active source: runtime")
    elif kind == "damaged":
        print("Codex runtime: damaged or locally modified")
        print("Codex active source: bundled")
        print(f"Codex runtime warning: {current['warning']}")
    elif kind == "bundled-preferred":
        print(
            f"Codex runtime: {current['runtime']} "
            f"(official source; bundled {bundled} preferred)"
        )
        print("Codex active source: bundled")
    else:
        print("Codex runtime: not installed")
        print("Codex active source: bundled")


def confirm(prompt: str, *, yes: bool) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        fail("operation requires interactive confirmation or --yes")
    if input(prompt + " [y/N] ").strip().lower() not in {"y", "yes"}:
        raise KeyboardInterrupt


def update_runtime(*, yes: bool) -> None:
    bundled = bundled_version()
    current = state()
    confirm(
        "Check the official OpenAI Codex release and install a newer compatible "
        "runtime if available? This action will make network requests; the "
        f"immutable bundled {bundled} remains the fallback.",
        yes=yes,
    )
    asset = latest_asset()
    if version_tuple(asset["version"]) <= version_tuple(bundled):
        print(
            f"Bundled Codex {bundled} is already at least as new as latest stable "
            f"{asset['version']}; no runtime update installed."
        )
        return
    if current.get("kind") == "runtime" and version_tuple(
        str(current["runtime"])
    ) >= version_tuple(asset["version"]):
        print(
            f"Optional Codex runtime {current['runtime']} is already at least as "
            f"new as latest stable {asset['version']}."
        )
        return
    with update_staging() as temp:
        archive = temp / asset["name"]
        final_url = download(asset, archive)
        package = temp / "package"
        extract(archive, package)
        package_metadata(package, asset)
        home, cwd = prepare_candidate_directories(temp)
        validate_candidate(package, asset["version"], home=home, cwd=cwd)
        publish(package, asset, final_url)
    print(
        f"Installed Codex runtime {asset['version']} "
        "(official source; Remote Dev review pending)."
    )
    print(f"Bundled fallback remains {bundled}.")


def remove_runtime_entry(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    try:
        info = path.lstat()
    except OSError as exc:
        fail(f"cannot inspect Codex runtime path for removal: {path}: {exc}")
    if info.st_uid != expected_owner():
        fail(f"Codex runtime path has unexpected owner: {path}")
    try:
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()
    except OSError as exc:
        fail(f"cannot remove Codex runtime path: {path}: {exc}")


def remove_runtime(*, yes: bool) -> None:
    if not ROOT.exists() and not ROOT.is_symlink():
        print("Codex runtime: not installed")
        return
    confirm("Remove the optional Codex runtime and use bundled fallback?", yes=yes)
    with runtime_lock():
        try:
            remove_runtime_entry(ROOT / "current")
            remove_runtime_entry(stamp_path())
            releases = ROOT / "releases"
            remove_runtime_entry(releases)
            releases.mkdir(mode=0o700)
        except OSError as exc:
            fail(f"cannot reset Codex runtime state after removal: {exc}")
    print("Optional Codex runtime removed; bundled fallback is active.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status")
    status.add_argument("--menu", action="store_true")
    commands.add_parser("resolve")
    commands.add_parser("verify")
    for name in ("install", "update", "remove"):
        sub = commands.add_parser(name)
        sub.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print_status(state(), menu=args.menu)
        elif args.command == "resolve":
            current = state()
            if current.get("verification_warning"):
                print(
                    "WARNING: optional Codex runtime passed full integrity "
                    "verification, but its verification stamp could not be "
                    f"persisted: {current['verification_warning']}",
                    file=sys.stderr,
                )
            if current["kind"] == "runtime":
                print(current["binary"])
            else:
                if current["kind"] == "damaged":
                    print(
                        "WARNING: optional Codex runtime damaged; using bundled "
                        f"fallback: {current['warning']}",
                        file=sys.stderr,
                    )
                print(BUNDLED)
        elif args.command == "verify":
            verify_runtime()
        elif args.command in {"install", "update"}:
            update_runtime(yes=args.yes)
        elif args.command == "remove":
            remove_runtime(yes=args.yes)
        return 0
    except OperationInterrupted as exc:
        print("Codex runtime operation cancelled.", file=sys.stderr)
        return 128 + exc.signum
    except KeyboardInterrupt:
        print("Codex runtime operation cancelled.", file=sys.stderr)
        return 130
    except ManagerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
