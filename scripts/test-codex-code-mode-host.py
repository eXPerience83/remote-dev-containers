#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import select
import subprocess
import time
import urllib.error
import urllib.request

HOST = os.environ.get("CODEX_CODE_MODE_HOST", "/usr/local/bin/codex-code-mode-host")
LISTEN_URL = "ws://127.0.0.1:0"
STARTUP_TIMEOUT_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 5.0
URL_PATTERN = re.compile(r"^ws://127\.0\.0\.1:(?P<port>[0-9]{1,5})$")


def process_error(process: subprocess.Popen[str], message: str) -> RuntimeError:
    detail = ""
    if process.poll() is not None and process.stderr is not None:
        detail = process.stderr.read().strip()
    if detail:
        message = f"{message}: {detail}"
    return RuntimeError(message)


def read_listen_url(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while True:
        if process.poll() is not None:
            raise process_error(process, "code-mode host exited before publishing its listen URL")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("timed out waiting for code-mode host listen URL")
        readable, _, _ = select.select([process.stdout], [], [], min(0.2, remaining))
        if not readable:
            continue
        line = process.stdout.readline().strip()
        if line:
            return line


def wait_until_ready(process: subprocess.Popen[str], listen_url: str) -> None:
    match = URL_PATTERN.fullmatch(listen_url)
    if match is None:
        raise RuntimeError(f"unexpected code-mode host listen URL: {listen_url!r}")
    port = int(match.group("port"))
    if not (1 <= port <= 65535):
        raise RuntimeError(f"invalid code-mode host listen port: {port}")

    ready_url = f"http://127.0.0.1:{port}/readyz"
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise process_error(process, "code-mode host exited before becoming ready")
        try:
            with urllib.request.urlopen(ready_url, timeout=0.5) as response:
                if response.status == 200:
                    return
                last_error = RuntimeError(f"unexpected readiness status: {response.status}")
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.05)

    raise RuntimeError(f"timed out waiting for {ready_url}: {last_error}")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def main() -> None:
    process = subprocess.Popen(
        [HOST, "--listen", LISTEN_URL],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        listen_url = read_listen_url(process)
        wait_until_ready(process, listen_url)
    finally:
        stop_process(process)


if __name__ == "__main__":
    main()
