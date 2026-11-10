#!/usr/bin/env python3
"""Image-level negative filesystem, env and FD test using the real Landlock policy.

Run only on a disposable CI/runtime-smoke container. Uses synthetic inputs and
never opens agent credentials. Deliberately does not use the real AGY binary.
"""
from __future__ import annotations

import fcntl
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

LIBRARY = Path("/usr/local/lib/remote-dev/browser-sandbox.py")
MODULE = importlib.util.spec_from_file_location("remote_dev_browser_sandbox_probe", LIBRARY)
if MODULE is None or MODULE.loader is None:
    raise SystemExit("Missing immutable browser sandbox module")
sandbox = importlib.util.module_from_spec(MODULE)
sys.modules[MODULE.name] = sandbox
MODULE.loader.exec_module(sandbox)

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
            [binary, "-e", JS_PROBE],
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
        shutil.rmtree(temp_dir)


if __name__ == "__main__":
    try:
        raise SystemExit(run_probe())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print("Real Landlock negative probe: unavailable (" +
              type(error).__name__ + ")", file=sys.stderr)
        raise SystemExit(1) from None
