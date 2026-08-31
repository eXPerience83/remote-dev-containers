#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import http.client
import os
import re
import select
import signal
import subprocess
import time
from collections.abc import Iterator
from typing import NoReturn

HOST = os.environ.get("CODEX_CODE_MODE_HOST", "/usr/local/bin/codex-code-mode-host")
LISTEN_URL = "grpc://127.0.0.1:0"
STARTUP_TIMEOUT_SECONDS = 5.0
READY_TIMEOUT_SECONDS = 5.0
MAX_HEALTH_BODY = 4096
URL_PATTERN = re.compile(r"^http://127\.0\.0\.1:(?P<port>[0-9]{1,5})$")


class ProbeDeadlineExceeded(TimeoutError):
    """The local health exchange exceeded its absolute readiness deadline."""


@contextlib.contextmanager
def wall_clock_deadline(deadline: float) -> Iterator[None]:
    """Interrupt blocking local HTTP I/O when the absolute deadline expires."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProbeDeadlineExceeded("code-mode host readiness deadline expired")
    alarm = getattr(signal, "SIGALRM", None)
    timer = getattr(signal, "ITIMER_REAL", None)
    if alarm is None or timer is None or not hasattr(signal, "setitimer"):
        raise RuntimeError("code-mode host smoke requires POSIX interval timers")
    previous_handler = signal.getsignal(alarm)
    previous_delay, previous_interval = signal.setitimer(timer, 0.0)
    started = time.monotonic()

    def expired(_signum: int, _frame: object) -> NoReturn:
        raise ProbeDeadlineExceeded("code-mode host readiness deadline expired")

    try:
        signal.signal(alarm, expired)
        signal.setitimer(timer, remaining)
        yield
    finally:
        signal.setitimer(timer, 0.0)
        signal.signal(alarm, previous_handler)
        if previous_delay > 0:
            elapsed = max(0.0, time.monotonic() - started)
            signal.setitimer(
                timer,
                max(1e-6, previous_delay - elapsed),
                previous_interval,
            )


def process_error(process: subprocess.Popen[str], message: str) -> RuntimeError:
    detail = ""
    if process.poll() is not None and process.stderr is not None:
        detail = process.stderr.read(4096).strip()
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

    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise process_error(process, "code-mode host exited before becoming ready")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        connection = http.client.HTTPConnection(
            "127.0.0.1", port, timeout=min(0.5, remaining)
        )
        try:
            with wall_clock_deadline(deadline):
                connection.request("GET", "/healthz")
                response = connection.getresponse()
                body = response.read(MAX_HEALTH_BODY + 1)
            if len(body) > MAX_HEALTH_BODY:
                raise RuntimeError("code-mode host health response exceeded size limit")
            if response.status == 200:
                return
            last_error = RuntimeError(f"unexpected readiness status: {response.status}")
        except OSError as exc:
            last_error = exc
        finally:
            connection.close()
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.05, remaining))

    raise RuntimeError(f"timed out waiting for code-mode host readiness: {last_error}")


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
