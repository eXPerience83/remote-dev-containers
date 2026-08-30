#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("remote-dev-codex-runtime.py")


def load_manager():
    spec = importlib.util.spec_from_file_location("codex_runtime_probe_manager", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status: int):
        self.status = status

    def read(self) -> bytes:
        return b""


class FakeConnection:
    def __init__(self, *, status: int = 200, request_error: Exception | None = None):
        self.status = status
        self.request_error = request_error
        self.closed = False
        self.requests: list[tuple[str, str]] = []

    def request(self, method: str, path: str) -> None:
        self.requests.append((method, path))
        if self.request_error is not None:
            raise self.request_error

    def getresponse(self) -> FakeResponse:
        return FakeResponse(self.status)

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(
        self,
        stdout: bytes,
        stderr: bytes = b"",
        *,
        poll_sequence: list[int | None] | None = None,
    ):
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        os.write(stdout_write, stdout)
        os.write(stderr_write, stderr)
        os.close(stdout_write)
        os.close(stderr_write)
        self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
        self.stderr = os.fdopen(stderr_read, "rb", buffering=0)
        self.returncode: int | None = None
        self.poll_sequence = list(poll_sequence or [])
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self) -> int | None:
        if self.poll_sequence:
            value = self.poll_sequence.pop(0)
            if value is not None:
                self.returncode = value
            return value
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.waited = True
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class CodexCodeModeProbeTests(unittest.TestCase):
    def setUp(self):
        self.m = load_manager()
        self.host = Path("/candidate/bin/codex-code-mode-host")
        self.cwd = Path("/candidate/cwd")
        self.home = Path("/candidate/home")

    def test_capability_parser_accepts_0150_and_0151_shapes(self):
        help_0150 = """\
Usage: codex-code-mode-host [OPTIONS]

Options:
      --listen <URL>
          Transport endpoint: `stdio`, `stdio://`, `ws://IP:PORT`, or
          `grpc://IP:PORT`.
  -h, --help
          Print help
"""
        help_0151 = """\
Usage: codex-code-mode-host [OPTIONS]

Options:
      --listen <URL>
          Transport endpoint: `stdio`, `stdio://`, or `grpc://IP:PORT`.
      --otel-trace-listen <URL>
          Optional WebSocket endpoint used only for traces.
  -h, --help
          Print help
"""
        self.assertEqual(
            self.m.code_mode_host_capabilities(help_0150),
            {"grpc", "websocket"},
        )
        self.assertEqual(
            self.m.code_mode_host_capabilities(help_0151),
            {"grpc"},
        )
        self.assertEqual(
            self.m.select_code_mode_host_transport(
                self.m.code_mode_host_capabilities(help_0150)
            ),
            "grpc",
        )
        self.assertEqual(
            self.m.select_code_mode_host_transport(
                self.m.code_mode_host_capabilities(help_0151)
            ),
            "grpc",
        )

    def test_capability_parser_ignores_unrelated_websocket_option(self):
        help_text = """\
Options:
      --listen <URL>
          Transport endpoint: `stdio` or `stdio://`.
      --otel-trace-listen <URL>
          Optional endpoint: `ws://IP:PORT`.
"""
        capabilities = self.m.code_mode_host_capabilities(help_text)
        self.assertEqual(capabilities, set())
        with self.assertRaisesRegex(self.m.ManagerError, "supported.*--listen"):
            self.m.select_code_mode_host_transport(capabilities)

    def test_published_listener_requires_expected_loopback_contract(self):
        self.assertEqual(
            self.m.code_mode_host_published_port(
                "grpc", "http://127.0.0.1:43210"
            ),
            43210,
        )
        self.assertEqual(
            self.m.code_mode_host_published_port(
                "websocket", "ws://127.0.0.1:43210"
            ),
            43210,
        )
        invalid = (
            ("grpc", "grpc://127.0.0.1:43210"),
            ("grpc", "http://0.0.0.0:43210"),
            ("grpc", "http://localhost:43210"),
            ("grpc", "http://127.0.0.1:0"),
            ("grpc", "http://127.0.0.1:65536"),
            ("grpc", "http://127.0.0.1:not-a-port"),
            ("websocket", "http://127.0.0.1:43210"),
            ("websocket", "ws://127.0.0.2:43210"),
        )
        for transport, published in invalid:
            with self.subTest(transport=transport, published=published):
                with self.assertRaisesRegex(self.m.ManagerError, "unexpected"):
                    self.m.code_mode_host_published_port(transport, published)

    def run_probe(
        self,
        process: FakeProcess,
        *,
        transport: str = "grpc",
        connection: FakeConnection | None = None,
        monotonic=None,
    ):
        connection = connection or FakeConnection()
        patches = [
            mock.patch.object(self.m, "require_candidate_path"),
            mock.patch.object(self.m.subprocess, "Popen", return_value=process),
            mock.patch.object(
                self.m.http.client, "HTTPConnection", return_value=connection
            ),
            mock.patch.object(self.m.time, "sleep", return_value=None),
        ]
        if monotonic is not None:
            patches.append(mock.patch.object(self.m.time, "monotonic", side_effect=monotonic))
        with patches[0], patches[1] as popen, patches[2], patches[3]:
            if len(patches) == 5:
                with patches[4]:
                    result = self.m.probe_host(
                        self.host, self.cwd, self.home, transport=transport
                    )
            else:
                result = self.m.probe_host(
                    self.host, self.cwd, self.home, transport=transport
                )
        return result, popen, connection

    def test_grpc_probe_uses_healthz_and_reaps_process(self):
        process = FakeProcess(b"http://127.0.0.1:43210\n")
        _result, popen, connection = self.run_probe(process)
        self.assertEqual(
            popen.call_args.args[0],
            [str(self.host), "--listen", "grpc://127.0.0.1:0"],
        )
        self.assertEqual(connection.requests, [("GET", "/healthz")])
        self.assertTrue(connection.closed)
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    def test_legacy_websocket_probe_is_explicit_and_bounded(self):
        process = FakeProcess(b"ws://127.0.0.1:43210\n")
        _result, popen, connection = self.run_probe(process, transport="websocket")
        self.assertEqual(
            popen.call_args.args[0],
            [str(self.host), "--listen", "ws://127.0.0.1:0"],
        )
        self.assertEqual(connection.requests, [("GET", "/readyz")])
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    def test_non_200_health_response_fails_and_reaps_process(self):
        process = FakeProcess(b"http://127.0.0.1:43210\n")
        connection = FakeConnection(status=503)
        with self.assertRaisesRegex(self.m.ManagerError, "did not become ready"):
            self.run_probe(
                process,
                connection=connection,
                monotonic=[0.0, 0.0, 0.0, 6.0],
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    def test_health_connection_timeout_fails_and_reaps_process(self):
        process = FakeProcess(b"http://127.0.0.1:43210\n")
        connection = FakeConnection(request_error=TimeoutError("synthetic timeout"))
        with self.assertRaisesRegex(self.m.ManagerError, "did not become ready"):
            self.run_probe(
                process,
                connection=connection,
                monotonic=[0.0, 0.0, 0.0, 6.0],
            )
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)

    def test_process_exit_after_publishing_listener_is_rejected(self):
        process = FakeProcess(
            b"http://127.0.0.1:43210\n",
            b"synthetic exit\n",
            poll_sequence=[None, 1],
        )
        with self.assertRaisesRegex(self.m.ManagerError, "exited before readiness"):
            self.run_probe(process, monotonic=[0.0, 0.0, 0.0])
        self.assertEqual(process.returncode, 1)

    def test_probe_output_limit_terminates_and_reaps_process(self):
        process = FakeProcess(b"x" * 128)
        with mock.patch.object(self.m, "MAX_PROBE_OUTPUT", 64):
            with self.assertRaisesRegex(self.m.ManagerError, "exceeded output limit"):
                self.run_probe(process, monotonic=[0.0, 0.0])
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)


if __name__ == "__main__":
    unittest.main()
