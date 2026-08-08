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
MAX_PROBE_OUTPUT = 1024 * 1024
TIMEOUT = 20
SCHEMA = 1
NOBODY = 65534


class ManagerError(RuntimeError):
    """A bounded admission or local-integrity check failed."""


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


def prepare_root() -> None:
    try:
        if ROOT.exists() or ROOT.is_symlink():
            real_dir(ROOT)
        else:
            ROOT.mkdir(parents=True, mode=0o700)
        ROOT.chmod(0o700)
    except OSError as exc:
        fail(f"cannot prepare Codex runtime root {ROOT}: {exc}")


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


def extract(archive_path: Path, destination: Path) -> None:
    try:
        destination.mkdir(mode=0o755)
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
                    output.mkdir(parents=True, exist_ok=True)
                    output.chmod(0o755)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
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


def drop_privileges() -> None:
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(NOBODY)
        os.setuid(NOBODY)


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
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        env=candidate_env(home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        preexec_fn=drop_privileges if os.name == "posix" else None,
    )
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
    return subprocess.CompletedProcess(
        argv,
        returncode,
        bytes(output[process.stdout]).decode("utf-8", errors="replace"),
        bytes(output[process.stderr]).decode("utf-8", errors="replace"),
    )


def probe_host(host: Path, cwd: Path, home: Path) -> None:
    process = subprocess.Popen(
        [str(host), "--listen", "ws://127.0.0.1:0"],
        cwd=cwd,
        env=candidate_env(home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        preexec_fn=drop_privileges if os.name == "posix" else None,
    )
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


def validate_candidate(package: Path, expected_version: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix="remote-dev-codex-home-"
    ) as home_text, tempfile.TemporaryDirectory(
        prefix="remote-dev-codex-cwd-"
    ) as cwd_text:
        home = Path(home_text)
        cwd = Path(cwd_text)
        if os.geteuid() == 0:
            os.chown(home, NOBODY, NOBODY)
            os.chown(cwd, NOBODY, NOBODY)
        home.chmod(0o700)
        cwd.chmod(0o700)
        result = candidate_run([str(package / "bin/codex"), "--version"], cwd, home)
        match = VERSION_RE.fullmatch(result.stdout.strip()) if result.returncode == 0 else None
        if not match or match.group(1) != expected_version:
            fail("candidate Codex version probe failed")
        help_result = candidate_run([str(package / "bin/codex"), "--help"], cwd, home)
        if help_result.returncode != 0 or any(
            flag not in help_result.stdout
            for flag in ("--sandbox", "--ask-for-approval")
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


def publish(package: Path, asset: dict[str, Any], final_url: str) -> None:
    expected_records = records(package)
    release_name = (
        f"{asset['version']}-{asset['sha256'][:16]}-{uuid.uuid4().hex[:8]}"
    )
    with runtime_lock():
        staging: Path | None = None
        try:
            releases = ROOT / "releases"
            if releases.exists() or releases.is_symlink():
                real_dir(releases)
            else:
                releases.mkdir(mode=0o700)
            releases.chmod(0o700)
            for old in releases.iterdir():
                if (
                    old.name.startswith(".candidate-")
                    and old.is_dir()
                    and not old.is_symlink()
                ):
                    shutil.rmtree(old, ignore_errors=True)
            previous_name = read_previous_name()
            staging = releases / f".candidate-{uuid.uuid4().hex}"
            final_release = releases / release_name
            staging.mkdir(mode=0o700)
            destination = staging / "package"
            shutil.copytree(package, destination)
            for path in [destination, *destination.rglob("*")]:
                if path.is_symlink():
                    fail("published Codex runtime cannot contain symlinks")
                if path.is_dir():
                    path.chmod(0o700)
                elif path.is_file():
                    path.chmod(0o700 if path.stat().st_mode & stat.S_IXUSR else 0o600)
            if records(destination) != expected_records:
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
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_path.chmod(0o600)
            os.replace(staging, final_release)
            pointer = ROOT / f".current-{uuid.uuid4().hex}"
            pointer.write_text(release_name + "\n", encoding="utf-8")
            pointer.chmod(0o600)
            os.replace(pointer, ROOT / "current")
            keep_names = {release_name}
            if previous_name:
                keep_names.add(previous_name)
            for old in releases.iterdir():
                if (
                    old.name not in keep_names
                    and old.is_dir()
                    and not old.is_symlink()
                    and not old.name.startswith(".candidate-")
                ):
                    shutil.rmtree(old, ignore_errors=True)
        except OSError as exc:
            fail(f"cannot publish Codex runtime: {exc}")
        finally:
            if staging is not None and staging.exists() and not staging.is_symlink():
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


def verify_package_files(package: Path, manifest: dict[str, Any]) -> set[str]:
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
        if info.st_size != size or file_sha(path) != sha:
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


def active_runtime() -> tuple[str, Path] | None:
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
        manifest = validate_manifest(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"Codex runtime manifest is invalid: {exc}")
    package = release / "package"
    real_dir(package)
    verify_package_files(package, manifest)
    metadata = package_metadata(package)
    version = manifest["version"]
    if metadata.get("version") != version:
        fail("Codex runtime version differs between package and private manifest")
    return version, package / "bin/codex"


def state() -> dict[str, Any]:
    bundled = bundled_version()
    if not ROOT.exists() and not ROOT.is_symlink():
        return {"kind": "bundled", "bundled": bundled}
    try:
        real_dir(ROOT)
        runtime = active_runtime()
    except ManagerError as exc:
        return {"kind": "damaged", "bundled": bundled, "warning": str(exc)}
    if runtime is None:
        return {"kind": "bundled", "bundled": bundled}
    runtime_version, binary = runtime
    if version_tuple(runtime_version) <= version_tuple(bundled):
        return {
            "kind": "bundled-preferred",
            "bundled": bundled,
            "runtime": runtime_version,
            "binary": binary,
        }
    return {
        "kind": "runtime",
        "bundled": bundled,
        "runtime": runtime_version,
        "binary": binary,
    }


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
    with tempfile.TemporaryDirectory(
        prefix="remote-dev-codex-update-"
    ) as text:
        temp = Path(text)
        temp.chmod(0o755)
        archive = temp / asset["name"]
        final_url = download(asset, archive)
        package = temp / "package"
        extract(archive, package)
        package_metadata(package, asset)
        validate_candidate(package, asset["version"])
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
    for name in ("install", "update", "remove"):
        sub = commands.add_parser(name)
        sub.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            print_status(state(), menu=args.menu)
        elif args.command == "resolve":
            current = state()
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
        elif args.command in {"install", "update"}:
            update_runtime(yes=args.yes)
        elif args.command == "remove":
            remove_runtime(yes=args.yes)
        return 0
    except KeyboardInterrupt:
        print("Codex runtime operation cancelled.", file=sys.stderr)
        return 130
    except ManagerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
