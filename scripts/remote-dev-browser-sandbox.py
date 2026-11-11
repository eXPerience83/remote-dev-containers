#!/usr/bin/env python3
"""Fail-closed, unprivileged Playwright MCP supervisor and cleanup guardian.

This code is installed immutable in the image and launched with image Python -I.
The root agent never passes its environment or inherited file descriptors to
Node/Chromium. No ports or project mounts are added.
"""
from __future__ import annotations

import ctypes
import os
import select
import time
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

UID = 61123
GID = 61123
IMAGE_PYTHON = "/usr/local/lib/remote-dev/python"
IMAGE_NODE = "/usr/local/lib/remote-dev/node"
MCP_ENTRY = "/opt/remote-dev/playwright/node_modules/@playwright/mcp/cli.js"
MCP_CONFIG = "/usr/share/remote-dev/playwright-mcp.json"
BROWSER_ASSETS = "/opt/remote-dev/playwright-browsers"
TMP_ROOT = "/run"
LL_CREATE, LL_ADD, LL_RESTRICT = 444, 445, 446  # x86_64 and aarch64
LL_VERSION, LL_PATH_RULE = 1, 1
PR_SET_PDEATHSIG, PR_SET_NO_NEW_PRIVS = 1, 38
PR_SET_DUMPABLE, PR_SET_CHILD_SUBREAPER = 4, 36

EXEC, WRITE, READ, READDIR = (1 << i for i in range(4))
RM_DIR, RM_FILE, MK_CHAR, MK_DIR, MK_REG, MK_SOCK, MK_FIFO = (
    1 << i for i in range(4, 11)
)
MK_BLOCK, MK_SYM, REFER, TRUNCATE, IOCTL_DEV = (
    1 << i for i in range(11, 16)
)
HANDLED = (1 << 16) - 1
READ_ONLY = READ | READDIR
READ_EXEC = READ_ONLY | EXEC
WRITE_DIR = (READ_ONLY | WRITE | RM_DIR | RM_FILE | MK_DIR | MK_REG |
             MK_SOCK | MK_FIFO | MK_SYM | REFER | TRUNCATE)
DEVICE = READ | WRITE | IOCTL_DEV

libc = ctypes.CDLL(None, use_errno=True)


class IsolationError(Exception):
    pass


class Interrupted(Exception):
    def __init__(self, signum: int):
        self.signum = signum


class PathRule(ctypes.Structure):
    _fields_ = [("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32)]


def syscall(number: int, *arguments: object) -> int:
    result = libc.syscall(number, *arguments)
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return int(result)


def landlock_abi() -> int:
    return syscall(LL_CREATE, 0, 0, LL_VERSION)


def rules(node: str, scratch: str) -> list[tuple[str, int]]:
    target = os.path.realpath(node)
    if (not target.startswith("/opt/remote-dev/mise/installs/node/")
            or not target.endswith("/bin/node")):
        raise IsolationError("unexpected Node location")
    if not scratch.startswith("/run/remote-dev-browser-"):
        raise IsolationError("unexpected scratch location")
    return [
        ("/usr", READ_EXEC), ("/bin", READ_EXEC),
        ("/lib", READ_EXEC), ("/lib64", READ_EXEC),
        ("/etc", READ_ONLY), ("/sys", READ_ONLY),
        # /proc contains other processes' argv. ttyd carries its Basic Auth
        # credential in argv, so never grant READ_FILE on all of /proc.
        # Node may inspect its own proc entry and these innocuous global stats.
        ("/proc", READDIR),
        ("/proc/self", READ_ONLY),
        ("/proc/thread-self", READ_ONLY),
        ("/proc/cpuinfo", READ), ("/proc/meminfo", READ),
        ("/proc/stat", READ), ("/proc/uptime", READ),
        ("/proc/loadavg", READ), ("/proc/version", READ),
        (os.path.dirname(target), READ_EXEC),
        ("/opt/remote-dev/playwright", READ_EXEC),
        (BROWSER_ASSETS, READ_EXEC),
        ("/dev/null", DEVICE), ("/dev/zero", DEVICE),
        ("/dev/random", DEVICE), ("/dev/urandom", DEVICE),
        ("/dev/shm", WRITE_DIR), (scratch, WRITE_DIR),
    ]


def landlock(node: str, scratch: str) -> None:
    # ABI 5 introduced ioctl device mediation; TrueNAS reported ABI 7.
    if landlock_abi() < 5:
        raise IsolationError("Landlock ABI below 5")
    mask = ctypes.c_uint64(HANDLED)
    fd = syscall(LL_CREATE, ctypes.byref(mask), ctypes.sizeof(mask), 0)
    try:
        for raw, rights in rules(node, scratch):
            path = os.path.realpath(raw)
            if not os.path.exists(path):
                if raw in {"/bin", "/lib", "/lib64", "/sys",
                           "/dev/zero", "/dev/random"}:
                    continue
                raise IsolationError("missing required sandbox path")
            is_dir = os.path.isdir(path)
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                if not is_dir:
                    rights &= READ | WRITE | EXEC | IOCTL_DEV
                attr = PathRule(rights, path_fd)
                syscall(LL_ADD, fd, LL_PATH_RULE, ctypes.byref(attr), 0)
            finally:
                os.close(path_fd)
        syscall(LL_RESTRICT, fd, 0)
    finally:
        os.close(fd)


def no_new_privileges() -> None:
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_NO_NEW_PRIVS failed")


def drop_privileges() -> None:
    os.setgroups([])
    os.setgid(GID)
    os.setuid(UID)
    no_new_privileges()
    if os.geteuid() != UID or os.getegid() != GID:
        raise IsolationError("UID/GID drop failed")


def secure_preexec(node: str, scratch: str, parent_pid: int) -> None:
    drop_privileges()
    # setuid/setgid may clear PDEATHSIG; establish it after the UID transition.
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "parent-death signal failed")
    landlock(node, scratch)
    if os.getppid() != parent_pid:
        raise IsolationError("browser supervisor died during startup")


def safe_env(scratch: str) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": scratch, "TMPDIR": scratch, "TMP": scratch, "TEMP": scratch,
        "XDG_CACHE_HOME": scratch + "/cache",
        "XDG_CONFIG_HOME": scratch + "/config",
        "XDG_DATA_HOME": scratch + "/data",
        "XDG_RUNTIME_DIR": scratch + "/runtime",
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "PLAYWRIGHT_BROWSERS_PATH": BROWSER_ASSETS,
        "PLAYWRIGHT_MCP_OUTPUT_DIR": scratch + "/output",
        "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1",
        "DO_NOT_TRACK": "1",
    }


def kill_group(group: int) -> None:
    try:
        os.killpg(group, signal.SIGKILL)
    except ProcessLookupError:
        pass


def adopted_children() -> list[int]:
    """Enumerate this subreaper's children, including adopted Chromium trees."""
    # Linux /proc children is provided by TrueNAS's kernel and GitHub CI.
    path = f"/proc/self/task/{os.getpid()}/children"
    return [int(value) for value in Path(path).read_text().split()]


def cleanup_browser_tree(child: subprocess.Popen[bytes] | None) -> None:
    """Reap Node and all descendants, including detached Chrome process groups."""
    if child is not None:
        kill_group(child.pid)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
    deadline = time.monotonic() + 6
    while True:
        pending = adopted_children()
        if not pending:
            return
        for pid in pending:
            try:
                group = os.getpgid(pid)
                # Never target the trusted guardian's own session/group.
                if group != os.getpgrp():
                    kill_group(group)
                else:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # Reap all descendants that have become direct children of this
        # subreaper, including Chromium child processes that called setsid().
        while True:
            try:
                reaped, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if reaped == 0:
                break
        if time.monotonic() >= deadline:
            raise IsolationError("browser child process cleanup timed out")
        time.sleep(0.05)


def guardian(lifeline_fd: int, scratch: str) -> int:
    """Trusted parent of MCP Node; subreaper for detached Chromium descendants."""
    if os.geteuid() != 0 or not scratch.startswith(
            "/run/remote-dev-browser-"):
        return 2
    child: subprocess.Popen[bytes] | None = None
    try:
        guardian_runtime_hardening()
        # Do not spawn a browser without an observable orphan cleanup contract.
        adopted_children()
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal_exit)
        node = os.path.realpath(IMAGE_NODE)
        parent_pid = os.getpid()
        child = subprocess.Popen(
            [node, MCP_ENTRY, "--config", MCP_CONFIG],
            cwd=scratch, env=safe_env(scratch),
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
            close_fds=True, start_new_session=True,
            preexec_fn=lambda: secure_preexec(node, scratch, parent_pid),
        )
        # Parent process keeps the lifeline writer. EOF means the supervisor
        # exited, including SIGKILL; the guardian and Node have independent
        # process groups, so an external client cannot kill them by accident.
        while True:
            code = child.poll()
            if code is not None:
                return code
            ready, _, _ = select.select([lifeline_fd], [], [], 0.1)
            if ready and not os.read(lifeline_fd, 4096):
                return 143
    except Interrupted as stop:
        return 128 + stop.signum
    finally:
        try:
            cleanup_browser_tree(child)
        finally:
            os.close(lifeline_fd)
            shutil.rmtree(scratch, ignore_errors=True)


def guardian_runtime_hardening() -> None:
    # Executing the immutable Python interpreter resets Linux dumpability.
    # Apply this *after exec*, before starting any untrusted browser process.
    no_new_privileges()
    if libc.prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "guardian non-dumpable failed")
    if libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "guardian subreaper unavailable")


def guardian_preexec() -> None:
    # The trusted root guardian starts without agent credentials and with NNP.
    # PR_SET_DUMPABLE must be applied again inside guardian_runtime_hardening
    # because execve resets it for ordinary executables.
    no_new_privileges()


def signal_exit(signum: int, _frame: object) -> None:
    raise Interrupted(signum)


def supervise() -> int:
    if os.geteuid() != 0 or os.environ.get("REMOTE_DEV_ROLE") not in {
            "codex", "antigravity"}:
        raise IsolationError("requires root agent role")
    if sys.platform != "linux" or os.uname().machine not in {
            "x86_64", "aarch64"}:
        raise IsolationError("unsupported architecture")
    if landlock_abi() < 5:
        raise IsolationError("Landlock unavailable")
    node = os.path.realpath(IMAGE_NODE)
    for path in (node, MCP_ENTRY, MCP_CONFIG):
        if not Path(path).is_file():
            raise IsolationError("required immutable browser component absent")
    if not Path(BROWSER_ASSETS).is_dir():
        raise IsolationError("browser assets absent")
    if os.path.islink(TMP_ROOT) or not stat.S_ISDIR(
            os.stat(TMP_ROOT).st_mode):
        raise IsolationError("unsafe /run")
    scratch = tempfile.mkdtemp(prefix="remote-dev-browser-", dir=TMP_ROOT)
    guard: subprocess.Popen[bytes] | None = None
    readfd = writefd = -1
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal_exit)
        os.chown(scratch, UID, GID)
        for leaf in ("runtime", "output"):
            target = os.path.join(scratch, leaf)
            os.mkdir(target, 0o700)
            os.chown(target, UID, GID)
        readfd, writefd = os.pipe()
        # The non-dumpable root guardian is a *parent* and subreaper of Node,
        # not Node's sibling. It inherits only MCP stdio, the private lifeline
        # read FD and a fixed safe environment; never the agent's credentials.
        guard = subprocess.Popen(
            [IMAGE_PYTHON, "-I", __file__, "--guardian", str(readfd), scratch],
            cwd=scratch, env=safe_env(scratch),
            stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
            pass_fds=(readfd,), close_fds=True, start_new_session=True,
            preexec_fn=guardian_preexec,
        )
        os.close(readfd)
        readfd = -1
        return guard.wait()
    except Interrupted as stop:
        return 128 + stop.signum
    finally:
        if readfd >= 0:
            os.close(readfd)
        # The close acts as a cancellation signal to the root subreaper,
        # including on SIGTERM. It kills both Node and detached Chromium.
        if writefd >= 0:
            os.close(writefd)
        if guard is not None:
            try:
                guard.wait(timeout=9)
            except subprocess.TimeoutExpired:
                guard.terminate()
                try:
                    guard.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    guard.kill()
                    guard.wait()
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "--guardian":
        try:
            return guardian(int(sys.argv[2]), sys.argv[3])
        except (ValueError, OSError, IsolationError, subprocess.SubprocessError):
            return 2
    if len(sys.argv) != 1:
        print("ERROR: browser MCP does not accept caller options", file=sys.stderr)
        return 2
    try:
        return supervise()
    except (IsolationError, OSError, subprocess.SubprocessError) as exc:
        # Never log the inherited environment or secrets.
        print("ERROR: isolated browser MCP unavailable (" +
              type(exc).__name__ + ")", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
