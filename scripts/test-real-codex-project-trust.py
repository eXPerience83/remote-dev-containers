#!/usr/bin/env python3
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import time


CODEX = Path(os.environ.get("REMOTE_DEV_BUNDLED_CODEX", "/usr/local/bin/codex"))


def start_thread(project: Path, trust: str) -> str:
    with tempfile.TemporaryDirectory() as home:
        config = Path(home, "config.toml")
        config.write_text("", encoding="utf-8")
        before = config.read_bytes()
        project_key = json.dumps(str(project))
        override = f'projects={{{project_key}={{trust_level="{trust}"}}}}'
        process = subprocess.Popen(
            [str(CODEX), "-c", override, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, "CODEX_HOME": home},
        )
        assert process.stdin is not None
        assert process.stdout is not None

        def send(message: dict) -> None:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()

        def receive(request_id: int) -> dict:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                readable, _, _ = select.select([process.stdout], [], [], 1)
                if not readable:
                    continue
                line = process.stdout.readline()
                if not line:
                    break
                response = json.loads(line)
                if response.get("id") == request_id:
                    return response
            raise AssertionError(f"Codex app-server did not answer request {request_id}")

        try:
            send({
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "remote_dev_policy_test",
                            "title": "Remote Dev policy test",
                            "version": "1",
                        }
                    },
            })
            initialized = receive(1)
            assert "result" in initialized, initialized
            send({"method": "initialized", "params": {}})
            send({
                    "method": "thread/start",
                    "id": 2,
                    "params": {"cwd": str(project), "ephemeral": True},
            })
            started = receive(2)
            assert "result" in started, started
            return started["result"]["approvalPolicy"]
        finally:
            process.terminate()
            process.wait(timeout=5)
            assert config.read_bytes() == before, "launch-scoped trust modified config.toml"


def main() -> None:
    version = subprocess.run(
        [str(CODEX), "--version"], check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()
    assert version == "codex-cli 0.150.0", version
    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace).resolve()
        assert start_thread(root, "trusted") == "on-request"
        assert start_thread(root, "untrusted") == "untrusted"
    print("Real Codex 0.150.0 project trust: trusted=on-request; untrusted=unless-trusted")


if __name__ == "__main__":
    main()
