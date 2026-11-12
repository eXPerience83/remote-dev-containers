#!/usr/bin/env python3
"""Image-level negative filesystem, env and FD test using the real Landlock policy.

Run only on a disposable CI/runtime-smoke container. Uses synthetic inputs and
never opens agent credentials. Deliberately does not use the real AGY binary.
"""
from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import select
import signal
import time
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIBRARY = Path("/usr/local/lib/remote-dev/browser-sandbox.py")


def load_sandbox():
    """Import the immutable runtime only during image execution, not unit import."""
    module_spec = importlib.util.spec_from_file_location(
        "remote_dev_browser_sandbox_probe", LIBRARY)
    if module_spec is None or module_spec.loader is None:
        raise SystemExit("Missing immutable browser sandbox module")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module

JS_PROBE = r"""
"use strict";
const fs = require("node:fs");
function assert(condition, message) {
  if (!condition) throw Error(message);
}
function denied(operation, label) {
  try { operation(); }
  catch (error) {
    if (error.code === "EACCES" || error.code === "EPERM") return;
    throw Error(label + " unexpectedly failed with " + error.code);
  }
  throw Error(label + " unexpectedly succeeded");
}
const status = fs.readFileSync("/proc/self/status", "utf8");
const field = key => status.match(new RegExp("^" + key + ":\\s*([^\\n]+)", "m"))?.[1]?.trim();
assert(process.getuid() === 61123 && process.getgid() === 61123, "identity");
assert(field("CapEff") === "0000000000000000", "effective capabilities");
assert(field("CapPrm") === "0000000000000000", "permitted capabilities");
assert(field("NoNewPrivs") === "1", "no-new-privileges");
for (const key of ["OPENAI_API_KEY", "GITHUB_TOKEN", "NODE_OPTIONS",
                   "HTTP_PROXY", "HTTPS_PROXY", "LD_PRELOAD",
                   "REMOTE_DEV_SYNTHETIC_SECRET"]) {
  assert(process.env[key] === undefined, "secret leaked: " + key);
}
assert(process.env.TMPDIR === process.env.HOME, "unexpected TMPDIR");
assert(process.env.TMPDIR.startsWith("/run/remote-dev-browser-"), "TMPDIR escaped /run");
assert(fs.readFileSync("/etc/passwd", "utf8").includes("root"), "system files not readable");
denied(() => fs.readdirSync("/workspace"), "workspace directory");
denied(() => fs.readdirSync("/root"), "agent root directory");
denied(() => fs.readdirSync("/tmp"), "global temporary directory");
const otherPid = process.argv[1];
assert(/^\d+$/.test(otherPid), "no synthetic ttyd PID");
denied(() => fs.readFileSync("/proc/" + otherPid + "/cmdline"),
       "synthetic ttyd credential in /proc");
denied(() => fs.readFileSync("/proc/" + otherPid + "/environ"),
       "synthetic ttyd environment in /proc");
try { fs.fstatSync(99); throw Error("inherited FD still usable"); }
catch (error) { if (error.code !== "EBADF") throw error; }
const probe = process.env.TMPDIR + "/write-probe";
fs.writeFileSync(probe, "synthetic-only");
assert(fs.readFileSync(probe, "utf8") === "synthetic-only", "private scratch unusable");
console.log("Real Landlock negative probe: PASS");
"""


def run_probe() -> int:
    if os.geteuid() != 0 or sys.platform != "linux":
        raise RuntimeError("root Linux smoke container required")
    if not Path("/workspace").is_dir():
        raise RuntimeError("workspace fixture directory required")
    binary = os.path.realpath(sandbox.IMAGE_NODE)
    if not Path(binary).is_file():
        raise RuntimeError("pinned Node executable missing")
    if sandbox.landlock_abi() < 5:
        raise RuntimeError("Landlock ABI is insufficient")
    temp_dir = tempfile.mkdtemp(prefix="remote-dev-browser-", dir="/run")
    fd = -1
    # Synthetic root process imitates ttyd's argv credentials. Never use any
    # real password or access the real ttyd process.
    synthetic_ttyd = subprocess.Popen(
        [sys.executable, "-I", "-c", "import time; time.sleep(45)",
         "synthetic-ttyd-user:synthetic-not-a-secret"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True,
    )
    try:
        os.chown(temp_dir, sandbox.UID, sandbox.GID)
        for leaf in ("runtime", "output"):
            item = os.path.join(temp_dir, leaf)
            os.mkdir(item, 0o700)
            os.chown(item, sandbox.UID, sandbox.GID)
        # Inheritable synthetic descriptor must be closed by the child launcher.
        canary = os.path.join(temp_dir, "synthetic-parent-fd")
        with open(canary, "wb") as f:
            f.write(b"nonsecret-test-data")
        source = os.open(canary, os.O_RDONLY)
        try:
            fd = fcntl.fcntl(source, fcntl.F_DUPFD, 99)
        finally:
            os.close(source)
        os.set_inheritable(fd, True)
        supervisor_pid = os.getpid()
        env = sandbox.safe_env(temp_dir)
        # Setting fake credentials on the parent must not affect the child.
        for key in ("OPENAI_API_KEY", "GITHUB_TOKEN", "NODE_OPTIONS",
                    "HTTP_PROXY", "HTTPS_PROXY", "LD_PRELOAD",
                    "REMOTE_DEV_SYNTHETIC_SECRET"):
            os.environ[key] = "synthetic-probe-only"
        result = subprocess.run(
            [binary, "-e", JS_PROBE, str(synthetic_ttyd.pid)],
            cwd=temp_dir,
            env=env,
            close_fds=True,
            start_new_session=True,
            preexec_fn=lambda: sandbox.secure_preexec(
                binary, temp_dir, supervisor_pid),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode or "Real Landlock negative probe: PASS" not in result.stdout:
            print("Real Landlock negative probe: FAIL", file=sys.stderr)
            print(result.stderr[-1400:], file=sys.stderr)
            return 1
        print("Real Landlock negative probe: PASS")
        return 0
    finally:
        if fd >= 0:
            os.close(fd)
        synthetic_ttyd.terminate()
        try:
            synthetic_ttyd.wait(timeout=3)
        except subprocess.TimeoutExpired:
            synthetic_ttyd.kill()
            synthetic_ttyd.wait()
        shutil.rmtree(temp_dir)


def sandbox_processes() -> set[int]:
    """Inspect only our synthetic MCP and Chromium processes, never their env."""
    found: set[int] = set()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if (b"@playwright/mcp/cli.js" in cmdline or
                b"/headless_shell" in cmdline or
                b"/chrome-headless-shell" in cmdline):
            found.add(int(proc.name))
    return found


def is_chromium(pid: int) -> bool:
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, OSError, PermissionError):
        return False
    return b"/headless_shell" in cmdline or b"/chrome-headless-shell" in cmdline


def descendants_of(pid: int) -> set[int]:
    """Walk only children of this fixture supervisor, not unrelated MCPs."""
    visited = {pid}
    pending = [pid]
    descendants: set[int] = set()
    while pending:
        parent = pending.pop()
        try:
            children = Path(f"/proc/{parent}/task/{parent}/children").read_text().split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        for child in children:
            if not child.isdecimal():
                raise RuntimeError("malformed process ancestry")
            number = int(child)
            if number not in visited:
                visited.add(number)
                descendants.add(number)
                pending.append(number)
                if len(visited) > 512:
                    raise RuntimeError("unexpectedly large browser process tree")
    return descendants


def parse_process_start_time(stat_line: str) -> int:
    """Extract Linux /proc/pid/stat field 22 after the parenthesized comm."""
    end = stat_line.rfind(") ")
    if end < 0:
        raise RuntimeError("malformed process identity")
    fields = stat_line[end + 2:].split()  # state is field 3 at index zero.
    if len(fields) < 20:
        raise RuntimeError("short process identity")
    return int(fields[19])


def process_start_time(pid: int) -> int | None:
    """Use PID + start ticks to distinguish reaping from PID reuse.

    A zombie still has /proc/pid/stat, and must NOT be treated as gone.
    """
    try:
        return parse_process_start_time(Path(f"/proc/{pid}/stat").read_text())
    except (FileNotFoundError, ProcessLookupError):
        return None


def lifecycle_probe(target: str = "supervisor") -> int:
    """Kill supervisor or guardian and verify descendant and scratch cleanup."""
    if target not in {"supervisor", "guardian"}:
        raise ValueError("unsupported lifecycle target")
    before_dirs = {p.name for p in Path("/run").glob("remote-dev-browser-*")}
    before_pids = sandbox_processes()
    role = os.environ.get("REMOTE_DEV_ROLE", "codex")
    if role not in ("codex", "antigravity"):
        role = "codex"
    proc = subprocess.Popen(
        ["/usr/local/bin/remote-dev-playwright-mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd="/",
        env=dict(os.environ, REMOTE_DEV_ROLE=role),
        close_fds=True,
    )
    next_id = 0
    buffer = b""

    def notify(method: str) -> None:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) +
                          "\n").encode())
        proc.stdin.flush()

    def request(method: str, params: dict) -> dict:
        nonlocal next_id, buffer
        next_id += 1
        msg = {"jsonrpc": "2.0", "id": next_id,
               "method": method, "params": params}
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("id") != next_id:
                    continue
                if "error" in obj:
                    raise RuntimeError("MCP protocol lifecycle request failed")
                return obj.get("result", {})
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([proc.stdout], [], [],
                                        min(0.5, remaining))
            if ready:
                data = os.read(proc.stdout.fileno(), 32768)
                if not data:
                    raise RuntimeError("MCP exited during lifecycle probe")
                buffer += data
            if proc.poll() is not None and not buffer:
                raise RuntimeError("MCP terminated before response")
        raise RuntimeError("MCP lifecycle request timed out")

    new_dirs: set[str] = set()
    managed_pids: set[int] = set()
    try:
        request("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "remote-dev-lifecycle-probe", "version": "1.0"},
        })
        notify("notifications/initialized")
        tools = request("tools/list", {})
        if not any(t.get("name") == "browser_navigate" for t in
                   tools.get("tools", [])):
            raise RuntimeError("browser_navigate unavailable")
        result = request("tools/call", {
            "name": "browser_navigate",
            "arguments": {"url": "data:text/html,<title>cleanup-fixture</title>"},
        })
        if result.get("isError"):
            raise RuntimeError("browser navigation failed before SIGKILL")
        new_dirs = {p.name for p in Path("/run").glob("remote-dev-browser-*")} - before_dirs
        managed_pids = sandbox_processes() - before_pids
        tree = descendants_of(proc.pid)
        chromium_pids = {pid for pid in tree
                         if pid in managed_pids and is_chromium(pid)
                         and process_start_time(pid) is not None}
        children = Path(
            f"/proc/{proc.pid}/task/{proc.pid}/children").read_text().split()
        if len(children) != 1:
            raise RuntimeError("expected one direct guardian child")
        guardian_pid = int(children[0])
        if guardian_pid not in tree:
            raise RuntimeError("guardian absent from supervisor process tree")
        tracked = {pid: birth for pid in (tree | managed_pids | {guardian_pid})
                   if (birth := process_start_time(pid)) is not None}
        if len(new_dirs) != 1 or not chromium_pids or guardian_pid not in tracked:
            raise RuntimeError("guardian/Chromium/profile absent before cleanup")
        # Deliberately do not close stdin: exercise the SIGKILL fallback.
        if target == "guardian":
            os.kill(guardian_pid, signal.SIGKILL)
        else:
            proc.kill()
        proc.wait(timeout=12)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            remaining_dirs = {p.name for p in
                              Path("/run").glob("remote-dev-browser-*")}
            # Any recorded /proc identity still present is a failure,
            # INCLUDING a zombie. A recycled PID has different start ticks.
            remaining_pids = {pid for pid, birth in tracked.items()
                              if process_start_time(pid) == birth}
            if not (new_dirs & remaining_dirs) and not remaining_pids:
                print(f"MCP SIGKILL {target} lifecycle: PASS")
                return 0
            time.sleep(0.1)
        raise RuntimeError("MCP guardian left unreaped descendants (including zombies) or scratch")
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()


if __name__ == "__main__":
    sandbox = load_sandbox()
    try:
        result = run_probe()
        if result == 0:
            result = lifecycle_probe("supervisor")
        if result == 0:
            result = lifecycle_probe("guardian")
        raise SystemExit(result)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("Real Landlock negative probe: unavailable (" +
              type(error).__name__ + ")", file=sys.stderr)
        raise SystemExit(1) from None
