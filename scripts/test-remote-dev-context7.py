#!/usr/bin/env python3
from __future__ import annotations

import contextlib
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


@contextlib.contextmanager
def codex_environment(home: Path):
    previous = {
        key: os.environ.get(key)
        for key in ("CODEX_HOME", "REMOTE_DEV_ROLE")
    }
    os.environ["CODEX_HOME"] = str(home)
    os.environ["REMOTE_DEV_ROLE"] = "codex"
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def assert_passive_status_no_network(module, home: Path) -> None:
    original_build_opener = module.build_opener

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("passive Context7 operation attempted network access")

    module.build_opener = fail_if_called
    try:
        with codex_environment(home):
            paths = module.Paths()
            if module.command_status(paths, argparse_namespace(menu=True)) != 0:
                raise AssertionError("passive Context7 status unexpectedly failed")
    finally:
        module.build_opener = original_build_opener


def assert_update_no_network(module, home: Path) -> None:
    original_build_opener = module.build_opener

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Context7 update attempted network access")

    module.build_opener = fail_if_called
    config = home / "config.toml"
    before = config.read_bytes()
    try:
        with codex_environment(home):
            paths = module.Paths()
            if module.command_update(paths, argparse_namespace(yes=True)) != 0:
                raise AssertionError("in-process Context7 update unexpectedly failed")
            if config.read_bytes() != before:
                raise AssertionError("in-process Context7 update unexpectedly rewrote configuration")
    finally:
        module.build_opener = original_build_opener


def assert_masked_interactive_key_prompt(module, home: Path) -> None:
    original_getpass = module.getpass.getpass
    original_stdin = sys.stdin
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
        with codex_environment(home):
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


def assert_main_cancelled_prompt_handling(module, home: Path) -> None:
    original_confirm = module.confirm
    original_argv = list(module.sys.argv)
    try:
        with codex_environment(home):
            module.sys.argv = ["remote-dev-context7", "remove"]
            for exception_type in (EOFError, KeyboardInterrupt):
                def cancelled(*_args, _exception_type=exception_type, **_kwargs):
                    raise _exception_type()

                module.confirm = cancelled
                if module.main() != 2:
                    raise AssertionError(f"{exception_type.__name__} was not mapped to Context7 cancellation status")
    finally:
        module.confirm = original_confirm
        module.sys.argv = original_argv


def assert_passive_diagnostic_categories(module, root: Path) -> None:
    # The doctor needs an actionable reason without reading or printing
    # credential files or exposing untrusted TOML content.
    scenarios = {
        "invalid": (
            '[mcp_servers.context7\n',
            "Codex config unreadable or invalid",
        ),
        "markers-malformed": (
            'model = "synthetic"\n' + START_MARKER + "\n",
            "Context7 ownership markers malformed",
        ),
        "conflict": (
            'model = "synthetic"\n' + START_MARKER + "\n" + END_MARKER + "\n",
            "Context7 ownership conflict",
        ),
        "managed-drift": (
            module.MANAGED_BLOCK.replace(
                module.CONTEXT7_ENDPOINT, "https://private.invalid/synthetic-secret", 1
            ),
            "managed Context7 contract drift",
        ),
    }
    for kind, (payload, reason) in scenarios.items():
        home = root / f"diagnostic-{kind}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        config.write_text(payload, encoding="utf-8")
        before = config.read_bytes()
        with codex_environment(home):
            line, code = module.status_line(module.Paths())
            state = module.inspect_config(module.Paths())
        if state.kind != kind or code != 3 or reason not in line:
            raise AssertionError(f"Context7 diagnostic classification failed: {kind}, {state.kind}")
        if "synthetic-secret" in line or "private.invalid" in line:
            raise AssertionError("Context7 diagnosis leaked untrusted TOML values")
        if config.read_bytes() != before:
            raise AssertionError("passive Context7 diagnosis changed private configuration")


def assert_specific_marker_diagnostics(module, root: Path) -> None:
    # The exact reason is derived from fixed marker positions only, never
    # from the content of unrelated MCPs, keys or TOML values.
    cases = {
        "missing-begin": (
            END_MARKER + "\n",
            "missing BEGIN marker",
        ),
        "missing-end": (
            START_MARKER + "\n",
            "missing END marker",
        ),
        "duplicate-begin": (
            START_MARKER + "\n" + START_MARKER + "\n" + END_MARKER + "\n",
            "duplicate BEGIN marker",
        ),
        "duplicate-end": (
            START_MARKER + "\n" + END_MARKER + "\n" + END_MARKER + "\n",
            "duplicate END marker",
        ),
        "reversed": (
            END_MARKER + "\n" + START_MARKER + "\n",
            "END marker precedes BEGIN marker",
        ),
        "begin-whitespace": (
            START_MARKER + "  \n" + END_MARKER + "\n",
            "BEGIN marker has extra whitespace",
        ),
        "end-whitespace": (
            START_MARKER + "\n" + END_MARKER + " \n",
            "END marker has extra whitespace",
        ),
        "duplicates-both": (
            START_MARKER + "\n" + END_MARKER + "\n"
            + START_MARKER + "\n" + END_MARKER + "\n",
            "duplicate BEGIN and END markers",
        ),
    }
    for label, (text, reason) in cases.items():
        home = root / f"marker-detail-{label}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        config.write_text('model = "synthetic"\n' + text, encoding="utf-8")
        before = config.read_bytes()
        with codex_environment(home):
            state = module.inspect_config(module.Paths())
            line, code = module.status_line(module.Paths())
        if state.kind != "markers-malformed" or code != 3:
            raise AssertionError(f"incorrect marker diagnosis for {label}")
        if reason not in line or "synthetic" in line:
            raise AssertionError(f"marker reason missing or content leaked for {label}")
        if config.read_bytes() != before:
            raise AssertionError(f"diagnosis wrote private configuration for {label}")


def assert_missing_begin_repair_fails_closed(module, root: Path) -> None:
    """The observed TrueNAS defect is one END with no BEGIN.

    Only an *otherwise intact* manager-owned Context7 block may be repaired;
    preserve Playwright and other user-owned config byte-for-byte, backup the
    original, do not change credentials and reject modified/partial blocks.
    """
    suffix = module.MANAGED_BLOCK[len(module.START_MARKER) + 1:]
    prefix = 'model = "synthetic"\n\n'
    other = (
        '\n[mcp_servers.playwright]\n'
        'command = "/usr/local/bin/remote-dev-playwright-mcp"\n'
        'enabled = true\n'
        '\n[mcp_servers.openaiDeveloperDocs]\n'
        'url = "https://example.invalid/official-docs"\n'
    )
    original = prefix + suffix + other
    home = root / "missing-begin-safe-repair"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text(original, encoding="utf-8")
    with codex_environment(home):
        state = module.inspect_config(module.Paths())
        if state.kind != "markers-malformed":
            raise AssertionError("missing-BEGIN fixture not detected")
        candidate = module.safe_missing_begin_candidate(state)
        expected = prefix + module.MANAGED_BLOCK + other
        if candidate != expected:
            raise AssertionError("missing-BEGIN recovery changed unrelated bytes")
    result = run_manager(home, "repair", "--yes")
    require_success(result, "exact missing-BEGIN repair")
    if config.read_text(encoding="utf-8") != expected:
        raise AssertionError("repair changed non-Context7 config")
    with codex_environment(home):
        if module.inspect_config(module.Paths()).kind != "managed":
            raise AssertionError("safe repair did not restore managed status")
    backup = home / "config.toml.remote-dev-context7.bak"
    if backup.read_text(encoding="utf-8") != original:
        raise AssertionError("safe repair did not preserve original private config")
    assert_private_file(backup)
    first = config.read_bytes()
    result = run_manager(home, "repair", "--yes")
    require_success(result, "missing-BEGIN repair idempotence")
    if config.read_bytes() != first:
        raise AssertionError("second repair unexpectedly rewrote config")

    bad_cases = {
        "modified-url": original.replace(
            module.CONTEXT7_ENDPOINT, "https://example.invalid/user-owned", 1),
        "modified-fields": original.replace(
            'required = false', 'required = true', 1),
        "partial-contract": original.replace(
            'enabled = true\nrequired = false\n',
            'required = false\n', 1),
        "end-only": prefix + module.END_MARKER + '\n' + other,
        "two-end-markers": original + module.END_MARKER + '\n',
        # Reproduces the observed TrueNAS structural layout: no BEGIN;
        # both enabled/required disagree with managed defaults, and two
        # separate MCP tables precede END. Never infer that disabling
        # Context7 is accidental or overwrite a user-chosen setting.
        "other-mcps-before-end": (
            prefix
            + suffix.replace("enabled = true", "enabled = false").replace(
                "required = false", "required = true"
            ).replace(
                module.END_MARKER + "\n",
                '[mcp_servers.playwright]\ncommand = "custom"\n'
                '[mcp_servers.openaiDeveloperDocs]\n'
                'url = "https://example.invalid/synthetic"\n'
                + module.END_MARKER + "\n",
            )
        ),
    }
    # No key, URL, custom MCP name or private text is ever returned by
    # status --menu; the operator receives fixed structural categories only.
    interleaved = bad_cases["other-mcps-before-end"]
    with codex_environment(root / "unused"):
        summary = module.missing_begin_layout_details(interleaved)
    if ("Context7 contract differs" not in summary
            or "other tables precede END" not in summary
            or "example.invalid" in summary or "custom" in summary):
        raise AssertionError("the interleaved TrueNAS regression did not give safe hints")
    for label, payload in bad_cases.items():
        unsafe_home = root / f"missing-begin-unsafe-{label}"
        unsafe_home.mkdir(mode=0o700)
        unsafe_config = unsafe_home / "config.toml"
        unsafe_config.write_text(payload, encoding="utf-8")
        with codex_environment(unsafe_home):
            state = module.inspect_config(module.Paths())
            if state.kind != "markers-malformed":
                raise AssertionError(f"unsafe fixture {label} classified unexpectedly")
            if module.safe_missing_begin_candidate(state) is not None:
                raise AssertionError(f"unsafe fixture {label} was accepted")
        result = run_manager(unsafe_home, "repair", "--yes")
        require_failure(result, f"unsafe missing-BEGIN repair {label}")
        if unsafe_config.read_text(encoding="utf-8") != payload:
            raise AssertionError(f"unsafe missing-BEGIN {label} mutated config")
        if (unsafe_home / "config.toml.remote-dev-context7.bak").exists():
            raise AssertionError(f"unsafe missing-BEGIN {label} wrote a backup")


def assert_interleaved_legacy_recovery(module, root: Path) -> None:
    """Live TrueNAS-inspired fixture: missing BEGIN, two legacy fields,
    two unrelated MCP tables before a displaced END marker.
    """
    prefix = 'model = "synthetic"\n\n'
    legacy = (
        '[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        'env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }\n'
    )
    other = (
        '\n[mcp_servers.playwright]\n'
        'command = "/usr/local/bin/remote-dev-playwright-mcp"\n'
        'enabled = true\n'
        '\n[mcp_servers.openaiDeveloperDocs]\n'
        'url = "https://example.invalid/synthetic-docs"\n'
    )
    original = prefix + legacy + other + module.END_MARKER + '\n'
    home = root / "interleaved-legacy-repair"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text(original, encoding="utf-8")
    with codex_environment(home):
        paths = module.Paths()
        state = module.inspect_config(paths)
        if state.kind != "markers-malformed":
            raise AssertionError("legacy test did not reproduce malformed markers")
        proposed = module.safe_interleaved_legacy_candidate(state)
        expected = prefix + module.MANAGED_BLOCK + other
        if proposed != expected:
            raise AssertionError("legacy recovery touched unrelated MCP table bytes")
        old_parsed = module.parse_toml(original, label="before")
        new_parsed = module.parse_toml(proposed, label="after")
        if module.without_context7(old_parsed) != module.without_context7(new_parsed):
            raise AssertionError("legacy recovery changed other TOML semantics")
    result = run_manager(home, "repair", "--yes")
    require_success(result, "explicit interleaved legacy repair")
    if config.read_text(encoding="utf-8") != expected:
        raise AssertionError("explicit repair did not preserve unrelated bytes")
    with codex_environment(home):
        paths = module.Paths()
        if module.inspect_config(paths).kind != "managed":
            raise AssertionError("legacy repair did not restore managed ownership")
        if module.status_line(paths) != ("Context7: configured (anonymous)", 0):
            raise AssertionError("recovered Context7 diagnostic not healthy")
    backup = home / "config.toml.remote-dev-context7.bak"
    if backup.read_text(encoding="utf-8") != original:
        raise AssertionError("legacy repair did not back up old user config")
    assert_private_file(backup)
    before_repeated = config.read_bytes()
    result = run_manager(home, "repair", "--yes")
    require_success(result, "legacy repair idempotence")
    if config.read_bytes() != before_repeated:
        raise AssertionError("repeating repair changed bytes")

    bad = {
        "url-drift": original.replace(
            module.CONTEXT7_ENDPOINT, "https://example.invalid/other", 1),
        "header-drift": original.replace(
            '"CONTEXT7_API_KEY" = "CONTEXT7_API_KEY"',
            '"OTHER" = "OTHER"', 1),
        "already-disabled": original.replace(
            legacy, legacy + 'enabled = false\n'),
        "required-custom": original.replace(
            legacy, legacy + 'required = true\n'),
        "extra-field": original.replace(
            legacy, legacy + 'startup_timeout_sec = 25\n'),
        "extra-comment": original.replace(
            legacy, legacy + '# user-managed option\n'),
        "reformatted-field": original.replace(
            'url = "' + module.CONTEXT7_ENDPOINT + '"',
            'url="' + module.CONTEXT7_ENDPOINT + '"', 1),
        "missing-END": original.replace(module.END_MARKER + '\n', ''),
        "duplicate-END": original + module.END_MARKER + '\n',
        "no-intervening-mcp": prefix + legacy + module.END_MARKER + '\n',
    }
    for name, payload in bad.items():
        badhome = root / f"interleaved-rejected-{name}"
        badhome.mkdir(mode=0o700)
        config = badhome / "config.toml"
        config.write_text(payload, encoding="utf-8")
        with codex_environment(badhome):
            state = module.inspect_config(module.Paths())
            if module.safe_interleaved_legacy_candidate(state) is not None:
                raise AssertionError(f"unsafe candidate accepted: {name}")
        result = run_manager(badhome, "repair", "--yes")
        require_failure(result, f"unsafe legacy case {name}")
        if config.read_text(encoding="utf-8") != payload:
            raise AssertionError(f"unsafe legacy case changed config: {name}")
        if (badhome / "config.toml.remote-dev-context7.bak").exists():
            raise AssertionError(f"unsafe legacy case wrote backup: {name}")


def assert_context7_browser_writer_serialization(module, root: Path) -> None:
    # This must be a real second process: browser-config locks the same
    # CODEX_HOME directory via a separate open file description.
    browser = MANAGER.with_name("remote-dev-browser-config.py")
    if not browser.is_file():
        raise AssertionError("browser MCP provisioning script is missing")
    home = root / "cross-provider-config-lock"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    original = 'model = "synthetic"\n'
    config.write_text(original, encoding="utf-8")
    env = {**os.environ, "CODEX_HOME": str(home),
           "REMOTE_DEV_ROLE": "codex"}
    with codex_environment(home):
        paths = module.Paths()
        with module.locked_codex_config(paths):
            contender = subprocess.run(
                [sys.executable, "-I", str(browser), "codex"],
                env=env, capture_output=True, text=True, timeout=7)
            if contender.returncode != 3 or "lock busy" not in contender.stderr:
                raise AssertionError("browser writer bypassed Context7 directory lock")
            if config.read_text(encoding="utf-8") != original:
                raise AssertionError("contending browser changed a locked config")
            state = module.inspect_config(paths)
            candidate = module.managed_candidate(state, require_existing=False)
            if not module.backup_and_replace_config(paths, state.text, candidate):
                raise AssertionError("Context7 update unexpectedly became a no-op")

    browser_after = subprocess.run(
        [sys.executable, "-I", str(browser), "codex"],
        env=env, capture_output=True, text=True, timeout=7)
    if browser_after.returncode:
        raise AssertionError("browser writer failed to configure after lock released")
    final = config.read_text(encoding="utf-8")
    if "[mcp_servers.playwright]" not in final:
        raise AssertionError("subsequent browser provisioner was lost")
    with codex_environment(home):
        if module.inspect_config(module.Paths()).kind != "managed":
            raise AssertionError("browser provisioning damaged managed Context7")


def assert_stale_context7_snapshot_never_overwrites(module, root: Path) -> None:
    # A non-cooperating writer may still edit the file. A stale snapshot
    # must fail before writing even a backup, despite holding our flock.
    home = root / "context7-stale-snapshot"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text('model = "original"\n', encoding="utf-8")
    with codex_environment(home):
        paths = module.Paths()
        with module.locked_codex_config(paths):
            state = module.inspect_config(paths)
            candidate = module.managed_candidate(state, require_existing=False)
            external = 'model = "other-writer"\n'
            config.write_text(external, encoding="utf-8")
            try:
                module.backup_and_replace_config(paths, state.text, candidate)
            except module.Context7Error as exc:
                if "changed during" not in str(exc):
                    raise AssertionError("unexpected stale snapshot rejection") from exc
            else:
                raise AssertionError("stale Context7 snapshot overwrote a concurrent edit")
            if config.read_text(encoding="utf-8") != external:
                raise AssertionError("external configuration edit was overwritten")
    if (home / "config.toml.remote-dev-context7.bak").exists():
        raise AssertionError("stale snapshot wrote a misleading backup")


def assert_legacy_recovery_requires_explicit_permission(module, root: Path) -> None:
    """Update --yes must never acquire a legacy Context7 block.
    Only install/repair --yes can authorize this exceptional recovery.
    """
    suffix = module.MANAGED_BLOCK[len(module.START_MARKER) + 1:]
    prefix = 'model = "synthetic"\n\n'
    interleaved = (
        '[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        'env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }\n'
        '\n[mcp_servers.playwright]\n'
        'command = "/usr/local/bin/remote-dev-playwright-mcp"\n'
        '\n[mcp_servers.openaiDeveloperDocs]\n'
        'url = "https://example.invalid/synthetic"\n'
        + module.END_MARKER + '\n'
    )
    for label, payload in (
        ("exact-block-missing-begin", prefix + suffix),
        ("interleaved-legacy-missing-begin", prefix + interleaved),
    ):
        home = root / f"explicit-only-{label}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        original = payload.encode("utf-8")
        config.write_bytes(original)
        with codex_environment(home):
            paths = module.Paths()
            state = module.inspect_config(paths)
            if state.kind != "markers-malformed":
                raise AssertionError(f"{label}: malformed markers not recognized")
            try:
                module.managed_candidate(state, require_existing=False)
            except module.Context7Error:
                pass
            else:
                raise AssertionError(f"{label}: implicit recovery unexpectedly allowed")
            try:
                module.apply_managed_config(paths, require_existing=False)
            except module.Context7Error:
                pass
            else:
                raise AssertionError(f"{label}: implicit apply unexpectedly allowed")
        result = run_manager(home, "update", "--yes")
        require_failure(result, f"{label}: update --yes must reject legacy recovery")
        if config.read_bytes() != original:
            raise AssertionError(f"{label}: unauthorized recovery modified config")
        if (home / "config.toml.remote-dev-context7.bak").exists():
            raise AssertionError(f"{label}: unauthorized recovery wrote backup")
        # A successful repair requires an explicit opt-in on the command path.
        result = run_manager(home, "repair", "--yes")
        require_success(result, f"{label}: repair --yes")
        with codex_environment(home):
            if module.inspect_config(module.Paths()).kind != "managed":
                raise AssertionError(f"{label}: explicit repair was not managed")


def assert_repair_preserves_mixed_newlines(module, root: Path) -> None:
    """Recover missing-BEGIN without normalizing unrelated CRLF/LF sections.

    Compare the actual file bytes, including the private preimage backup.
    """
    suffix = module.MANAGED_BLOCK[len(module.START_MARKER) + 1:]
    prefix = 'model = "synthetic"\r\nprofile = "test"\r\n\r\n'
    trailing = (
        '\r\n[mcp_servers.playwright]\r\n'
        'command = "custom-playwright"\r\n'
        'enabled = false\r\n'
    )
    legacy = (
        '[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        'env_http_headers = { "CONTEXT7_API_KEY" = "CONTEXT7_API_KEY" }\n'
    )
    docs = (
        '\r\n[mcp_servers.playwright]\r\n'
        'command = "custom-playwright"\r\n'
        '[mcp_servers.openaiDeveloperDocs]\r\n'
        'url = "https://example.invalid/synthetic-docs"\r\n'
    )
    cases = (
        ("exact", prefix + suffix + trailing,
         prefix + module.MANAGED_BLOCK + trailing),
        ("interleaved", prefix + legacy + docs + module.END_MARKER + '\n',
         prefix + module.MANAGED_BLOCK + docs),
    )
    for label, original, expected in cases:
        home = root / f"mixed-newlines-{label}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        before = original.encode("utf-8")
        config.write_bytes(before)
        with codex_environment(home):
            parsed = module.inspect_config(module.Paths())
            if parsed.kind != "markers-malformed":
                raise AssertionError(f"{label}: mixed newlines not accepted as input")
            if parsed.text.encode("utf-8") != before:
                raise AssertionError(f"{label}: reader normalized original line endings")
        result = run_manager(home, "repair", "--yes")
        require_success(result, f"{label}: mixed newline repair")
        if config.read_bytes() != expected.encode("utf-8"):
            raise AssertionError(f"{label}: mixed newline bytes were normalized")
        backup = home / "config.toml.remote-dev-context7.bak"
        if backup.read_bytes() != before:
            raise AssertionError(f"{label}: backup bytes did not match original")
        assert_private_file(backup)
        with codex_environment(home):
            if module.inspect_config(module.Paths()).kind != "managed":
                raise AssertionError(f"{label}: recovered block did not validate")


def assert_nested_headers_recovery_and_preflight(module, root: Path) -> None:
    """Reproduce the actual TrueNAS report without reading private test input.

    Legacy Context7 headers are a separate nested TOML table; BEGIN missing,
    enabled/required absent, and two unrelated MCP tables ahead of END.
    """
    ctx = (
        '[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        '\n[mcp_servers.context7.env_http_headers]\n'
    )
    unrelated = (
        '\r\n[mcp_servers.playwright]\r\n'
        'command = "custom-playwright"\r\n'
        'enabled = false\r\n'
        '\r\n[mcp_servers.openaiDeveloperDocs]\r\n'
        'url = "https://example.invalid/docs"\r\n'
    )
    prefix = 'model = "synthetic"\r\n\r\n'
    for variant, header in (
        ("bare", 'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n'),
        ("quoted", '"CONTEXT7_API_KEY" = "CONTEXT7_API_KEY"\n'),
    ):
        home = root / f"nested-real-{variant}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        original = prefix + ctx + header + unrelated + module.END_MARKER + "\n"
        config.write_bytes(original.encode("utf-8"))
        key_dir = home / ".remote-dev-context7"
        key_dir.mkdir(mode=0o700)
        key = key_dir / "api-key"
        key.write_text(SYNTHETIC_KEY, encoding="utf-8")
        key.chmod(0o600)
        key_before = key.read_bytes()
        old_bytes = config.read_bytes()

        with codex_environment(home):
            state = module.inspect_config(module.Paths())
            if state.kind != "markers-malformed":
                raise AssertionError(f"{variant}: true legacy format classified incorrectly")
            recovered = module.safe_nested_headers_legacy_candidate(state)
            expected = prefix + module.MANAGED_BLOCK + unrelated
            if recovered != expected:
                raise AssertionError(f"{variant}: recovered bytes touched other MCPs")
            if module.without_context7(module.parse_toml(original, label="before")) != (
                module.without_context7(module.parse_toml(recovered, label="after"))
            ):
                raise AssertionError("nested recovery changed unrelated TOML semantics")
            if module.recognized_legacy_recovery(state) != expected:
                raise AssertionError("nested recovery not considered by central planner")

        plan = run_manager(home, "plan")
        require_success(plan, f"{variant}: dry-run safe recovery plan")
        if "REINSTALLABLE" not in plan.stdout or "reinstall --yes" not in plan.stdout:
            raise AssertionError("safe recovery preview lacks actionable recommendation")
        status = run_manager(home, "status", "--menu")
        if status.returncode != 3 or "reinstall Context7" not in status.stdout:
            raise AssertionError("doctor status does not recommend safe repair")
        if config.read_bytes() != old_bytes or key.read_bytes() != key_before:
            raise AssertionError("passive preview modified private files")
        if (home / "config.toml.remote-dev-context7.bak").exists():
            raise AssertionError("read-only plan created a backup")

        update = run_manager(home, "update", "--yes")
        require_failure(update, f"{variant}: update must not claim legacy ownership")
        if config.read_bytes() != old_bytes:
            raise AssertionError("update illegally rewrote legacy TOML")

        repair = run_manager(home, "repair", "--yes")
        require_success(repair, f"{variant}: explicit nested recovery")
        if config.read_bytes() != expected.encode("utf-8"):
            raise AssertionError("recovery did not preserve unrelated raw bytes")
        backup = home / "config.toml.remote-dev-context7.bak"
        if backup.read_bytes() != old_bytes:
            raise AssertionError("private backup differs from exact preimage")
        assert_private_file(backup)
        if key.read_bytes() != key_before:
            raise AssertionError("recovery unexpectedly changed existing API key")
        assert_private_file(key)

        newstatus = run_manager(home, "status", "--menu")
        require_success(newstatus, f"{variant}: recovered status")
        if newstatus.stdout.strip() != "Context7: configured (API key stored)":
            raise AssertionError("recovered status not healthy or lost API key")
        if "ALREADY MANAGED" not in run_manager(home, "plan").stdout:
            raise AssertionError("recovered plan did not mark Context7 healthy")

        prev = config.read_bytes()
        repeat = run_manager(home, "repair", "--yes")
        require_success(repeat, f"{variant}: recovery idempotence")
        if config.read_bytes() != prev or key.read_bytes() != key_before:
            raise AssertionError("repeated repair was not idempotent")


def assert_nested_headers_recovery_fails_closed(module, root: Path) -> None:
    ctx = (
        '[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        '\n[mcp_servers.context7.env_http_headers]\n'
        'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n'
    )
    other = (
        '\n[mcp_servers.playwright]\ncommand = "user-owned"\n'
        '\n[mcp_servers.openaiDeveloperDocs]\n'
        'url = "https://example.invalid/docs"\n'
    )
    original = 'model = "safe"\n' + ctx + other + module.END_MARKER + '\n'
    bad_cases = {
        "endpoint-custom": original.replace(
            module.CONTEXT7_ENDPOINT, "https://example.invalid/custom", 1),
        "key-custom": original.replace(
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"',
            'CONTEXT7_API_KEY = "OTHER"', 1),
        "enabled-custom": original.replace(
            f'url = "{module.CONTEXT7_ENDPOINT}"\n',
            f'url = "{module.CONTEXT7_ENDPOINT}"\nenabled = false\n', 1),
        "required-custom": original.replace(
            f'url = "{module.CONTEXT7_ENDPOINT}"\n',
            f'url = "{module.CONTEXT7_ENDPOINT}"\nrequired = true\n', 1),
        "nested-extra-key": original.replace(
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n',
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\nOTHER = "PRIVATE"\n', 1),
        "nested-comment": original.replace(
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n',
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n# custom user note\n', 1),
        "custom-url-format": original.replace(
            f'url = "{module.CONTEXT7_ENDPOINT}"',
            f'url="{module.CONTEXT7_ENDPOINT}"', 1),
        "extra-headers": original.replace(
            '[mcp_servers.playwright]\n',
            '[mcp_servers.context7.extra]\nfoo = "bar"\n'
            '[mcp_servers.playwright]\n', 1),
        "missing-end": original.replace(module.END_MARKER + '\n', ''),
        "duplicate-end": original + module.END_MARKER + '\n',
        "wrong-marker": original.replace(module.END_MARKER, '# END OUTSIDER'),
        "no-other-mcp": 'model = "safe"\n' + ctx + module.END_MARKER + '\n',
        "extra-field": original.replace(
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n',
            'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n'
            'startup_timeout_sec = 15\n', 1),
    }
    for label, payload in bad_cases.items():
        home = root / f"nested-denied-{label}"
        home.mkdir(mode=0o700)
        config = home / "config.toml"
        config.write_bytes(payload.encode("utf-8"))
        preimage = config.read_bytes()
        with codex_environment(home):
            state = module.inspect_config(module.Paths())
            if module.safe_nested_headers_legacy_candidate(state) is not None:
                raise AssertionError(f"{label}: unsafe layout accepted")
        plan = run_manager(home, "plan")
        # The strict legacy *repair* must reject every mutated fixture.
        # The separate, explicit *reinstall* can reset Context7-owned fields
        # if it can prove that other MCP definitions remain intact.
        if label == "duplicate-end":
            if plan.returncode != 3 or "BLOCKED" not in plan.stdout:
                raise AssertionError(f"{label}: ambiguous markers were reinstallable")
        elif plan.returncode != 0 or "REINSTALLABLE" not in plan.stdout:
            raise AssertionError(f"{label}: isolated reinstall should be available")
        result = run_manager(home, "repair", "--yes")
        require_failure(result, f"{label}: unsafe repair")
        if config.read_bytes() != preimage:
            raise AssertionError(f"{label}: unsafe recovery overwrote config")
        if (home / "config.toml.remote-dev-context7.bak").exists():
            raise AssertionError(f"{label}: failed recovery wrote backup")


def assert_passive_preview_rejects_fifo_key(module, root: Path) -> None:
    """A FIFO key without a writer must not hang passive status or plan."""
    home = root / "nested-fifo-key"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    config.write_text(
        'model = "test"\n[mcp_servers.context7]\n'
        f'url = "{module.CONTEXT7_ENDPOINT}"\n'
        '\n[mcp_servers.context7.env_http_headers]\n'
        'CONTEXT7_API_KEY = "CONTEXT7_API_KEY"\n'
        '\n[mcp_servers.playwright]\ncommand = "user-owned"\n'
        + module.END_MARKER + '\n',
        encoding="utf-8",
    )
    before = config.read_bytes()
    key_dir = home / ".remote-dev-context7"
    key_dir.mkdir(mode=0o700)
    os.mkfifo(key_dir / "api-key", mode=0o600)
    for args in (("plan",), ("status", "--menu")):
        # run_manager already enforces a 20s bound; use a shorter bound here
        # to prove the FIFO is rejected without blocking on a writer.
        result = subprocess.run(
            [sys.executable, str(MANAGER), *args],
            text=True, capture_output=True,
            env={**os.environ, "CODEX_HOME": str(home),
                 "REMOTE_DEV_ROLE": "codex"},
            timeout=4,
            check=False,
        )
        if result.returncode != 3:
            raise AssertionError(f"FIFO key {args} did not report unsafe status")
        if args[0] == "plan" and "BLOCKED" not in result.stdout:
            raise AssertionError("plan did not block unsafe key state")
    if config.read_bytes() != before:
        raise AssertionError("passive FIFO diagnosis changed config")
    if (home / "config.toml.remote-dev-context7.bak").exists():
        raise AssertionError("passive FIFO diagnosis wrote backup")


def assert_scoped_reinstallation(module, root: Path) -> None:
    """Reinstall means rebuilding Context7's registration, not patching old fields."""
    common = (
        '\n[mcp_servers.playwright]\ncommand = "playwright"\n'
        '\n[mcp_servers.openaiDeveloperDocs]\nurl = "https://example.invalid/docs"\n'
    )
    layouts = {
        "nested": (
            '[mcp_servers.context7]\nurl = "https://example.invalid/old"\n'
            'enabled = false\n\n[mcp_servers.context7.env_http_headers]\n'
            'CONTEXT7_API_KEY = "OTHER"\n' + common + module.END_MARKER + '\n'),
        "inline": (
            '[mcp_servers.context7]\nurl = "https://example.invalid/old"\n'
            'env_http_headers = { KEY = "VALUE" }\n'
            'required = true\n' + common),
        "managed-drift": (
            module.START_MARKER + '\n'
            '[mcp_servers.context7]\nurl = "https://example.invalid/old"\n'
            'enabled = false\n' + module.END_MARKER + '\n' + common),
    }
    prefix = 'model = "synthetic"\r\n\r\n'
    for label, body in layouts.items():
        home = root / ("scoped-reinstall-" + label)
        home.mkdir(mode=0o700)
        path = home / "config.toml"
        original = prefix + body
        path.write_bytes(original.encode("utf-8"))
        with codex_environment(home):
            state = module.inspect_config(module.Paths())
            candidate = module.scoped_reinstall_candidate(state)
            if candidate is None:
                raise AssertionError(f"{label}: safe scoped reinstall unavailable")
            before = module.parse_toml(original, label="before")
            after = module.parse_toml(candidate, label="after")
            if module.without_context7(before) != module.without_context7(after):
                raise AssertionError(f"{label}: other MCP changed")
            if module.inspect_config_candidate(candidate) != "managed":
                raise AssertionError(f"{label}: new MCP registration not managed")
        plan = run_manager(home, "plan")
        require_success(plan, f"{label}: reinstall preview")
        if "REINSTALLABLE" not in plan.stdout:
            raise AssertionError("plan did not recommend reinstall")
        if path.read_bytes() != original.encode("utf-8"):
            raise AssertionError("read-only plan modified private config")
        result = run_manager(home, "reinstall", "--yes")
        require_success(result, f"{label}: reinstall")
        with codex_environment(home):
            state = module.inspect_config(module.Paths())
            if state.kind != "managed":
                raise AssertionError(f"{label}: reinstall not managed")
        if (home / "config.toml.remote-dev-context7.bak").read_bytes() != original.encode("utf-8"):
            raise AssertionError(f"{label}: backup not exact")
        saved = path.read_bytes()
        require_success(run_manager(home, "reinstall", "--yes"), "idempotent reinstall")
        if path.read_bytes() != saved:
            raise AssertionError("reinstallation is not idempotent")

    # Never let a malformed inline MCP table, duplicate owner marker or fake
    # table-like content in user values expand the scope.
    unsafe = {
        "inline-root": 'mcp_servers = { context7 = { url = "custom" } }\n',
        "duplicate-marker": (
            '[mcp_servers.context7]\nurl = "custom"\n'
            + module.END_MARKER + '\n' + module.END_MARKER + '\n'),
        "unknown-marker-position": (
            module.START_MARKER + '\nmodel = "custom"\n'
            '[mcp_servers.context7]\nurl = "custom"\n'),
    }
    for label, body in unsafe.items():
        home = root / ("scoped-reinstall-unsafe-" + label)
        home.mkdir(mode=0o700)
        path = home / "config.toml"
        path.write_text(body, encoding="utf-8")
        with codex_environment(home):
            if module.scoped_reinstall_candidate(module.inspect_config(module.Paths())) is not None:
                raise AssertionError(f"{label}: unsafe scope permitted")
        result = run_manager(home, "reinstall", "--yes")
        require_failure(result, f"{label}: unsafe reinstall")
        if path.read_text(encoding="utf-8") != body:
            raise AssertionError(f"{label}: unsafe scope modified TOML")


def assert_scoped_reinstall_retains_prior_backups(module, root: Path) -> None:
    """Multiple changed registrations retain both original rollback states."""
    home = root / "scoped-reinstall-rollback-history"
    home.mkdir(mode=0o700)
    config = home / "config.toml"
    prefix = 'model = "synthetic"\n'
    original = prefix + '[mcp_servers.context7]\nurl = "https://one.example/mcp"\n'
    config.write_text(original, encoding="utf-8")
    require_success(run_manager(home, "reinstall", "--yes"), "initial scoped reinstall backup")
    first_backup = home / "config.toml.remote-dev-context7.bak"
    if first_backup.read_text(encoding="utf-8") != original:
        raise AssertionError("initial rollback preimage incorrect")
    second = prefix + '[mcp_servers.context7]\nurl = "https://two.example/mcp"\n'
    config.write_text(second, encoding="utf-8")
    require_success(run_manager(home, "reinstall", "--yes"), "second scoped reinstall backup")
    history = list(home.glob("config.toml.remote-dev-context7.bak.*"))
    if len(history) != 1 or history[0].read_text(encoding="utf-8") != second:
        raise AssertionError("later rollback preimage was not retained separately")
    if first_backup.read_text(encoding="utf-8") != original:
        raise AssertionError("later reinstall overwrote original rollback")
    assert_private_file(first_backup)
    assert_private_file(history[0])


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

        assert_passive_diagnostic_categories(load_manager_module(), root)
        assert_specific_marker_diagnostics(load_manager_module(), root)
        assert_missing_begin_repair_fails_closed(load_manager_module(), root)
        assert_interleaved_legacy_recovery(load_manager_module(), root)
        assert_context7_browser_writer_serialization(load_manager_module(), root)
        assert_stale_context7_snapshot_never_overwrites(load_manager_module(), root)
        assert_legacy_recovery_requires_explicit_permission(load_manager_module(), root)
        assert_repair_preserves_mixed_newlines(load_manager_module(), root)
        assert_nested_headers_recovery_and_preflight(load_manager_module(), root)
        assert_nested_headers_recovery_fails_closed(load_manager_module(), root)
        assert_passive_preview_rejects_fifo_key(load_manager_module(), root)
        assert_scoped_reinstallation(load_manager_module(), root)
        assert_scoped_reinstall_retains_prior_backups(load_manager_module(), root)

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
        assert_main_cancelled_prompt_handling(module, home)

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
        result = run_manager(unmanaged_home, "remove", "--yes")
        require_failure(result, "unmanaged Context7 removal protection")
        if unmanaged_config.read_text(encoding="utf-8") != unmanaged_text:
            raise AssertionError("remove modified an unowned Context7 configuration")

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