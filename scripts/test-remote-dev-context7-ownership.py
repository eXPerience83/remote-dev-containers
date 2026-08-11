#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "scripts" / "remote-dev-context7.py"
START_MARKER = "# BEGIN REMOTE DEV MANAGED CONTEXT7"
END_MARKER = "# END REMOTE DEV MANAGED CONTEXT7"


def run_manager(home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(MANAGER), *arguments],
        env={**os.environ, "CODEX_HOME": str(home), "REMOTE_DEV_ROLE": "codex"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )


def load_manager_module():
    spec = importlib.util.spec_from_file_location("remote_dev_context7_ownership", MANAGER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {MANAGER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_ping_json_shape(module) -> None:
    original_build_opener = module.build_opener
    current = {"payload": b'{"status":"ok","message":"pong"}'}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def geturl() -> str:
            return module.CONTEXT7_PING

        @staticmethod
        def read(limit: int) -> bytes:
            return current["payload"][:limit]

    class FakeOpener:
        @staticmethod
        def open(request, *, timeout: int):
            if request.get_full_url() != "https://mcp.context7.com/ping":
                raise AssertionError("Context7 ping endpoint contract changed unexpectedly")
            if timeout != 10:
                raise AssertionError("Context7 ping timeout contract changed unexpectedly")
            return FakeResponse()

    def fake_build_opener(*_args):
        return FakeOpener()

    try:
        module.build_opener = fake_build_opener
        module.hosted_ping()
        for invalid_payload in (b"[]", b'"pong"', b"1", b"null"):
            current["payload"] = invalid_payload
            try:
                module.hosted_ping()
            except module.Context7Error:
                pass
            except Exception as exc:
                raise AssertionError(
                    f"non-object Context7 ping JSON escaped as {type(exc).__name__} instead of Context7Error"
                ) from exc
            else:
                raise AssertionError("non-object Context7 ping JSON was accepted")
    finally:
        module.build_opener = original_build_opener


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-ownership-") as temp:
        root = Path(temp)

        anonymous_home = root / "anonymous"
        anonymous_home.mkdir(mode=0o700)
        install = run_manager(anonymous_home, "install", "--yes", "--anonymous")
        if install.returncode != 0:
            raise AssertionError(
                f"anonymous install failed: {install.returncode}\n{install.stdout}\n{install.stderr}"
            )
        key_lookup = run_manager(anonymous_home, "key-file", "--active")
        if key_lookup.returncode != 5 or key_lookup.stdout:
            raise AssertionError(
                "healthy managed anonymous state must return internal key-file status 5 with no path"
            )

        spoof_home = root / "marker-spoof"
        spoof_home.mkdir(mode=0o700)
        spoof_config = spoof_home / "config.toml"
        spoof_text = f'''model = "gpt-test"
notes = """
{START_MARKER}
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
{END_MARKER}
"""
'''
        spoof_config.write_text(spoof_text, encoding="utf-8")
        repair = run_manager(spoof_home, "repair", "--yes")
        if repair.returncode == 0:
            raise AssertionError("marker-looking text inside a TOML multiline string was treated as owned config")
        if spoof_config.read_text(encoding="utf-8") != spoof_text:
            raise AssertionError("manager modified TOML containing only marker-looking string data")
        status = run_manager(spoof_home, "status", "--menu")
        if status.returncode != 3 or "damaged" not in status.stdout:
            raise AssertionError("marker-looking string data did not fail closed in passive status")

        rebind_home = root / "remove-rebind"
        rebind_home.mkdir(mode=0o700)
        rebind_config = rebind_home / "config.toml"
        rebind_text = f'''[mcp_servers.other]
command = "other-mcp"
{START_MARKER}
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
env_http_headers = {{ "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }}
enabled = true
required = false
{END_MARKER}
args = ["--would-rebind"]
'''
        rebind_config.write_text(rebind_text, encoding="utf-8")
        removal = run_manager(rebind_home, "remove", "--yes")
        if removal.returncode == 0:
            raise AssertionError("remove accepted a managed drift that would rebind trailing TOML keys")
        if rebind_config.read_text(encoding="utf-8") != rebind_text:
            raise AssertionError("failed removal changed unrelated Codex TOML semantics")
        if "would change unrelated Codex configuration" not in removal.stderr:
            raise AssertionError("unsafe removal did not report the bounded semantic-preservation error")

        assert_ping_json_shape(load_manager_module())

    print("Context7 ownership edge-case regressions: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())