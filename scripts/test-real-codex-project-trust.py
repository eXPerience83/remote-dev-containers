#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import tempfile
import time


CODEX = Path(os.environ.get("REMOTE_DEV_BUNDLED_CODEX", "/usr/local/bin/codex"))
BOUNDARY_VALIDATOR = Path(
    os.environ.get(
        "REMOTE_DEV_CODEX_PROJECT_BOUNDARY_VALIDATOR",
        "/usr/local/bin/validate-codex-project-boundary",
    )
)


def expected_cli_version(release_tag: str) -> str:
    match = re.fullmatch(r"rust-v(\d+\.\d+\.\d+)", release_tag)
    if match is None:
        raise SystemExit(
            f"expected a Codex release tag like rust-v0.150.0, got {release_tag!r}"
        )
    return f"codex-cli {match.group(1)}"


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
            send(
                {
                    "method": "initialize",
                    "id": 1,
                    "params": {
                        "clientInfo": {
                            "name": "remote_dev_policy_test",
                            "title": "Remote Dev policy test",
                            "version": "1",
                        }
                    },
                }
            )
            initialized = receive(1)
            assert "result" in initialized, initialized
            send({"method": "initialized", "params": {}})
            send(
                {
                    "method": "thread/start",
                    "id": 2,
                    "params": {"cwd": str(project), "ephemeral": True},
                }
            )
            started = receive(2)
            assert "result" in started, started
            return started["result"]["approvalPolicy"]
        finally:
            process.terminate()
            process.wait(timeout=5)
            assert config.read_bytes() == before, "launch-scoped trust modified config.toml"


def run_boundary_validator(
    project: Path, ceiling: Path, config_text: str = ""
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="remote-dev-real-codex-boundary-") as home:
        config = Path(home, "config.toml")
        config.write_text(config_text, encoding="utf-8")
        before = config.read_bytes()
        result = subprocess.run(
            [
                str(BOUNDARY_VALIDATOR),
                "--codex-binary",
                str(CODEX),
                "--cwd",
                str(project),
                "--ceiling",
                str(ceiling),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "CODEX_HOME": home},
        )
        assert config.read_bytes() == before, "boundary validation modified config.toml"
        return result


def assert_real_boundary_contract(root: Path) -> None:
    project = root / "project"
    project.mkdir()

    clean = run_boundary_validator(project, root)
    assert clean.returncode == 0, clean.stderr
    assert clean.stdout == "", clean.stdout

    # The managed set override is intentionally narrow. If a user policy later
    # applies include_only without the required variable, Codex would remove the
    # ceiling from model-reachable shell commands; the pre-launch probe must
    # detect that exact effective-policy outcome and fail closed.
    filtered = run_boundary_validator(
        project,
        root,
        '[shell_environment_policy]\ninclude_only = ["PATH", "HOME"]\n',
    )
    assert filtered.returncode == 2, filtered.stderr
    assert "filters out the required Git ceiling" in filtered.stderr, filtered.stderr


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} CODEX_RELEASE_TAG")
    expected_version = expected_cli_version(sys.argv[1])
    version = subprocess.run(
        [str(CODEX), "--version"], check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()
    assert version == expected_version, version
    assert BOUNDARY_VALIDATOR.is_file(), BOUNDARY_VALIDATOR

    with tempfile.TemporaryDirectory() as workspace:
        root = Path(workspace).resolve()
        assert start_thread(root, "trusted") == "on-request"
        assert start_thread(root, "untrusted") == "untrusted"

    with tempfile.TemporaryDirectory() as workspace:
        assert_real_boundary_contract(Path(workspace).resolve())

    print(
        f"Real {expected_version} project trust and effective Git-ceiling config probe: OK"
    )


if __name__ == "__main__":
    main()
