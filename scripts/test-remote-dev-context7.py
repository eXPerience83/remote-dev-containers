#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
MANAGER = ROOT / "scripts" / "remote-dev-context7.py"
SYNTHETIC_KEY = "ctx7-test-key-do-not-use"
START_MARKER = "# BEGIN REMOTE DEV MANAGED CONTEXT7"
END_MARKER = "# END REMOTE DEV MANAGED CONTEXT7"


def run_manager(
    home: Path,
    *arguments: str,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CODEX_HOME": str(home),
            "REMOTE_DEV_ROLE": "codex",
        }
    )
    if extra_env:
        environment.update(extra_env)
    return subprocess.run(
        [sys.executable, str(MANAGER), *arguments],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=20,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise AssertionError(
            f"{label} failed with {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def require_failure(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode == 0:
        raise AssertionError(f"{label} unexpectedly succeeded\nstdout:\n{result.stdout}")


def load_manager_module():
    spec = importlib.util.spec_from_file_location("remote_dev_context7", MANAGER)
    if spec is None or spec.loader is None:
        raise AssertionError(f"could not load {MANAGER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_private_file(path: Path) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise AssertionError(f"{path} mode is {mode:o}, expected 600")


def assert_passive_status_no_network(module, home: Path) -> None:
    original_build_opener = module.build_opener

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("passive Context7 operation attempted network access")

    module.build_opener = fail_if_called
    old_home = os.environ.get("CODEX_HOME")
    old_role = os.environ.get("REMOTE_DEV_ROLE")
    try:
        os.environ["CODEX_HOME"] = str(home)
        os.environ["REMOTE_DEV_ROLE"] = "codex"
        paths = module.Paths()
        if module.command_status(paths, argparse_namespace(menu=True)) != 0:
            raise AssertionError("passive Context7 status unexpectedly failed")
    finally:
        module.build_opener = original_build_opener
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
        if old_role is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = old_role


def assert_update_no_network(module, home: Path) -> None:
    original_build_opener = module.build_opener

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Context7 update attempted network access")

    module.build_opener = fail_if_called
    old_home = os.environ.get("CODEX_HOME")
    old_role = os.environ.get("REMOTE_DEV_ROLE")
    config = home / "config.toml"
    before = config.read_bytes()
    try:
        os.environ["CODEX_HOME"] = str(home)
        os.environ["REMOTE_DEV_ROLE"] = "codex"
        paths = module.Paths()
        if module.command_update(paths, argparse_namespace(yes=True)) != 0:
            raise AssertionError("in-process Context7 update unexpectedly failed")
        if config.read_bytes() != before:
            raise AssertionError("in-process current update unexpectedly rewrote configuration")
    finally:
        module.build_opener = original_build_opener
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
        if old_role is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = old_role


def assert_masked_interactive_key_prompt(module, home: Path) -> None:
    original_getpass = module.getpass.getpass
    original_stdin = sys.stdin
    old_home = os.environ.get("CODEX_HOME")
    old_role = os.environ.get("REMOTE_DEV_ROLE")
    calls: list[tuple[str, str | None]] = []
    expected_prompt = "Context7 API key (optional; blank keeps the current key or uses anonymous access): "

    class TtyInput:
        @staticmethod
        def isatty() -> bool:
            return True

    def fake_getpass(prompt: str, *, echo_char: str | None = None) -> str:
        calls.append((prompt, echo_char))
        return SYNTHETIC_KEY

    try:
        module.getpass.getpass = fake_getpass
        module.sys.stdin = TtyInput()
        os.environ["CODEX_HOME"] = str(home)
        os.environ["REMOTE_DEV_ROLE"] = "codex"
        action, value = module.choose_key(
            module.Paths(),
            argparse_namespace(anonymous=False, api_key_stdin=False, yes=False),
        )
        if action != "replace" or value != SYNTHETIC_KEY:
            raise AssertionError("interactive Context7 key prompt did not return the supplied synthetic key")
        if calls != [(expected_prompt, "*")]:
            raise AssertionError(f"interactive Context7 key prompt is not masked with '*': {calls!r}")
    finally:
        module.getpass.getpass = original_getpass
        module.sys.stdin = original_stdin
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
        if old_role is None:
            os.environ.pop("REMOTE_DEV_ROLE", None)
        else:
            os.environ["REMOTE_DEV_ROLE"] = old_role


def main() -> int:
    if not MANAGER.is_file():
        raise AssertionError(f"missing Context7 manager: {MANAGER}")

    with tempfile.TemporaryDirectory(prefix="remote-dev-context7-test-") as temp:
        root = Path(temp)

        home = root / "preserve"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        original = '''model = "gpt-test"

[mcp_servers.other]
command = "other-mcp"
args = ["--safe"]
'''
        config.write_text(original, encoding="utf-8")

        result = run_manager(home, "install", "--yes", "--anonymous")
        require_success(result, "anonymous install")
        installed = config.read_text(encoding="utf-8")
        if original not in installed:
            raise AssertionError("install did not preserve unrelated Codex config byte-for-byte")
        if installed.count(START_MARKER) != 1 or installed.count(END_MARKER) != 1:
            raise AssertionError("install did not create exactly one managed Context7 block")
        if 'url = "https://mcp.context7.com/mcp"' not in installed:
            raise AssertionError("managed block does not use the reviewed hosted endpoint")
        if 'env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }' not in installed:
            raise AssertionError("managed block does not map the Context7 API-key header to its private environment variable")
        if "required = false" not in installed:
            raise AssertionError("Context7 must remain non-fatal to Codex startup")
        assert_private_file(config)

        first_bytes = config.read_bytes()
        result = run_manager(home, "repair", "--yes")
        require_success(result, "idempotent repair")
        if config.read_bytes() != first_bytes:
            raise AssertionError("repeated repair changed an already-current config")

        result = run_manager(home, "status", "--menu")
        require_success(result, "anonymous status")
        if result.stdout.strip() != "Context7: configured (anonymous)":
            raise AssertionError(f"unexpected anonymous status: {result.stdout!r}")

        drifted = config.read_text(encoding="utf-8").replace(
            'url = "https://mcp.context7.com/mcp"',
            'url = "https://example.invalid/mcp"',
            1,
        )
        config.write_text(drifted, encoding="utf-8")
        result = run_manager(home, "status", "--menu")
        if result.returncode != 3 or "damaged" not in result.stdout:
            raise AssertionError("managed contract drift was not reported as damaged")
        result = run_manager(home, "repair", "--yes")
        require_success(result, "repair managed contract drift")
        repaired = config.read_text(encoding="utf-8")
        if 'https://example.invalid/mcp' in repaired or original not in repaired:
            raise AssertionError("repair did not restore only the managed contract")

        result = run_manager(
            home,
            "install",
            "--yes",
            "--api-key-stdin",
            input_text=SYNTHETIC_KEY + "\n",
        )
        require_success(result, "API-key install")
        key_file = home / ".remote-dev-context7" / "api-key"
        if key_file.read_text(encoding="utf-8") != SYNTHETIC_KEY:
            raise AssertionError("stored synthetic API key differs")
        assert_private_file(key_file)
        state_mode = stat.S_IMODE(key_file.parent.stat().st_mode)
        if state_mode != 0o700:
            raise AssertionError(f"Context7 private state mode is {state_mode:o}, expected 700")
        if SYNTHETIC_KEY in config.read_text(encoding="utf-8"):
            raise AssertionError("API key leaked into Codex config")
        if SYNTHETIC_KEY in result.stdout or SYNTHETIC_KEY in result.stderr:
            raise AssertionError("API key leaked into manager output")

        result = run_manager(home, "status")
        require_success(result, "key-backed status")
        if "API key stored" not in result.stdout or SYNTHETIC_KEY in result.stdout + result.stderr:
            raise AssertionError("status did not report key presence safely")

        result = run_manager(home, "key-file", "--active")
        require_success(result, "active key-file lookup")
        if Path(result.stdout.strip()) != key_file:
            raise AssertionError("key-file lookup returned an unexpected path")

        os.chmod(key_file, 0o644)
        result = run_manager(home, "status", "--menu")
        if result.returncode != 3 or "unsafe" not in result.stdout:
            raise AssertionError("unsafe API-key permissions were not detected")
        result = run_manager(home, "key-file", "--active")
        if result.returncode != 3 or result.stdout:
            raise AssertionError("unsafe API-key state was exposed to the Codex wrapper")
        os.chmod(key_file, 0o600)

        before_offline = config.read_bytes()
        dead_network = {
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
        }
        result = run_manager(home, "status", extra_env=dead_network)
        require_success(result, "offline passive status")
        result = run_manager(home, "update", "--yes", extra_env=dead_network)
        require_success(result, "offline hosted-contract update")
        if config.read_bytes() != before_offline:
            raise AssertionError("current update unexpectedly rewrote configuration")
        if "network: not used" not in result.stdout:
            raise AssertionError("update did not make its no-network behavior explicit")

        module = load_manager_module()
        assert_masked_interactive_key_prompt(module, home)
        assert_update_no_network(module, home)
        assert_passive_status_no_network(module, home)

        result = run_manager(home, "remove", "--yes")
        require_success(result, "managed removal")
        after_remove = config.read_text(encoding="utf-8")
        if START_MARKER in after_remove or END_MARKER in after_remove:
            raise AssertionError("remove left managed Context7 markers behind")
        if original not in after_remove:
            raise AssertionError("remove changed unrelated Codex config")
        if key_file.exists() or key_file.is_symlink():
            raise AssertionError("remove left the owned API-key file behind")
        backup = home / "config.toml.remote-dev-context7.bak"
        if not backup.is_file():
            raise AssertionError("config mutation did not create the private rollback backup")
        assert_private_file(backup)

        result = run_manager(home, "status", "--menu")
        require_success(result, "post-remove status")
        if result.stdout.strip() != "Context7: not configured":
            raise AssertionError("post-remove state is not reported as unconfigured")

        unmanaged_home = root / "unmanaged"
        unmanaged_home.mkdir(mode=0o700)
        unmanaged_config = unmanaged_home / "config.toml"
        unmanaged_text = '''[mcp_servers.context7]
url = "https://example.invalid/user-owned"
'''
        unmanaged_config.write_text(unmanaged_text, encoding="utf-8")
        result = run_manager(unmanaged_home, "install", "--yes", "--anonymous")
        require_failure(result, "unmanaged Context7 protection")
        if unmanaged_config.read_text(encoding="utf-8") != unmanaged_text:
            raise AssertionError("manager modified an unowned Context7 configuration")
        result = run_manager(unmanaged_home, "status", "--menu")
        require_success(result, "unmanaged status")
        if "unmanaged configuration" not in result.stdout:
            raise AssertionError("unmanaged Context7 state is not reported distinctly")

        malformed_home = root / "malformed"
        malformed_home.mkdir(mode=0o700)
        malformed_config = malformed_home / "config.toml"
        malformed_text = f'''model = "safe"
{START_MARKER}
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
'''
        malformed_config.write_text(malformed_text, encoding="utf-8")
        result = run_manager(malformed_home, "repair", "--yes")
        require_failure(result, "malformed marker protection")
        if malformed_config.read_text(encoding="utf-8") != malformed_text:
            raise AssertionError("repair modified config with ambiguous ownership markers")

        role_home = root / "role"
        role_home.mkdir(mode=0o700)
        result = subprocess.run(
            [sys.executable, str(MANAGER), "status"],
            env={**os.environ, "CODEX_HOME": str(role_home), "REMOTE_DEV_ROLE": "launcher"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
        require_failure(result, "non-Codex role rejection")

        valid_mcp_get = json.dumps(
            {
                "name": "context7",
                "enabled": True,
                "transport": {
                    "type": "streamable_http",
                    "url": "https://mcp.context7.com/mcp",
                    "bearer_token_env_var": None,
                    "http_headers": None,
                    "env_http_headers": {"CONTEXT7_API_KEY": "CONTEXT7_API_KEY"},
                },
            }
        )
        module.validate_codex_mcp_get(valid_mcp_get)
        invalid_mcp_gets = (
            "not-json",
            json.dumps([{"name": "context7"}]),
            json.dumps({"name": "context70", "enabled": True, "transport": {}}),
            json.dumps(
                {
                    "name": "context7",
                    "enabled": True,
                    "transport": {
                        "type": "streamable_http",
                        "url": "https://example.invalid/mcp",
                        "bearer_token_env_var": None,
                        "http_headers": None,
                        "env_http_headers": {"CONTEXT7_API_KEY": "CONTEXT7_API_KEY"},
                    },
                }
            ),
        )
        for invalid_mcp_get in invalid_mcp_gets:
            try:
                module.validate_codex_mcp_get(invalid_mcp_get)
            except module.Context7Error:
                pass
            else:
                raise AssertionError("structured Codex MCP-get validator accepted invalid Context7 evidence")

        try:
            module._NoRedirect().redirect_request(None, None, 302, "Found", {}, "http://127.0.0.1/")
        except module.Context7Error:
            pass
        else:
            raise AssertionError("Context7 ping redirect handler allowed a redirect")

        assert_passive_status_no_network(module, home)

    print("Context7 Codex integration lifecycle regressions: OK")
    return 0


def argparse_namespace(**values):
    class Namespace:
        pass

    namespace = Namespace()
    for key, value in values.items():
        setattr(namespace, key, value)
    return namespace


if __name__ == "__main__":
    raise SystemExit(main())