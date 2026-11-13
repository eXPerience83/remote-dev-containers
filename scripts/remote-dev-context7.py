#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import fcntl
import getpass
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


CONTEXT7_ENDPOINT = "https://mcp.context7.com/mcp"
CONTEXT7_PING = "https://mcp.context7.com/ping"
CONTEXT7_ENV = "CONTEXT7_API_KEY"
START_MARKER = "# BEGIN REMOTE DEV MANAGED CONTEXT7"
END_MARKER = "# END REMOTE DEV MANAGED CONTEXT7"
MANAGED_BLOCK = f'''{START_MARKER}
[mcp_servers.context7]
url = "{CONTEXT7_ENDPOINT}"
env_http_headers = {{ "CONTEXT7_API_KEY" = "{CONTEXT7_ENV}" }}
enabled = true
required = false
{END_MARKER}
'''
MANAGED_CONTRACT = {
    "url": CONTEXT7_ENDPOINT,
    "env_http_headers": {"CONTEXT7_API_KEY": CONTEXT7_ENV},
    "enabled": True,
    "required": False,
}
MAX_CONFIG_BYTES = 2 * 1024 * 1024
CONFIG_LOCK_WAIT_SECONDS = 2.0  # Match browser-config's directory flock timeout.
MAX_KEY_BYTES = 16 * 1024
MAX_PING_BYTES = 4096
BUNDLED_CODEX = Path("/usr/local/bin/codex")


class Context7Error(RuntimeError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Context7Error("Context7 ping attempted a redirect; refusing to follow it")


class ConfigState:
    def __init__(
        self,
        *,
        text: str,
        kind: str,
        span: tuple[int, int] | None = None,
        detail: str = "",
    ) -> None:
        self.text = text
        self.kind = kind
        self.span = span
        self.detail = detail


class Paths:
    def __init__(self) -> None:
        raw_home = os.environ.get("CODEX_HOME", "/root/.codex")
        self.home = Path(raw_home)
        if not self.home.is_absolute():
            raise Context7Error("CODEX_HOME must be an absolute path")
        self.config = self.home / "config.toml"
        self.backup = self.home / "config.toml.remote-dev-context7.bak"
        self.state_dir = self.home / ".remote-dev-context7"
        self.key = self.state_dir / "api-key"


def validate_role() -> None:
    role = os.environ.get("REMOTE_DEV_ROLE", "codex")
    if role != "codex":
        raise Context7Error(f"Context7 manager is available only for REMOTE_DEV_ROLE=codex; got {role}")


def validate_home(paths: Paths, *, create: bool = False) -> None:
    try:
        if paths.home.exists() or paths.home.is_symlink():
            info = paths.home.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise Context7Error(f"CODEX_HOME must be a real directory: {paths.home}")
        elif create:
            paths.home.mkdir(parents=True, mode=0o700)
    except OSError as exc:
        raise Context7Error(f"could not validate CODEX_HOME: errno {exc.errno}") from exc


def read_regular_text(path: Path, *, max_bytes: int) -> str:
    try:
        if not path.exists() and not path.is_symlink():
            return ""
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise Context7Error(f"refusing non-regular or symlinked file: {path}")
        if info.st_size > max_bytes:
            raise Context7Error(f"file exceeds the supported size limit: {path}")
        # newline="" keeps original CRLF and LF bytes; universal newline
        # translation would silently rewrite unrelated MCP entries on repair.
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise Context7Error(f"file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise Context7Error(f"could not read local Context7 state: errno {exc.errno}") from exc


def marker_span(text: str) -> tuple[int, int] | None:
    lines = text.splitlines(keepends=True)
    starts = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == START_MARKER
    ]
    ends = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") == END_MARKER
    ]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise Context7Error("Context7 ownership markers are malformed or duplicated")
    start_offset = sum(len(line) for line in lines[: starts[0]])
    end_offset = sum(len(line) for line in lines[: ends[0] + 1])
    return start_offset, end_offset


def marker_layout_reason(text: str) -> str:
    """Explain malformed ownership markers using only fixed, non-secret labels.

    Preserve the exact marker-matching rule used by marker_span(). Never
    include private config lines, paths or parser exception details.
    """
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line == START_MARKER]
    ends = [i for i, line in enumerate(lines) if line == END_MARKER]
    if len(starts) > 1 and len(ends) > 1:
        return "duplicate BEGIN and END markers"
    if len(starts) > 1:
        return "duplicate BEGIN marker"
    if len(ends) > 1:
        return "duplicate END marker"
    if not starts:
        if any(line.strip() == START_MARKER for line in lines):
            return "BEGIN marker has extra whitespace"
        return "missing BEGIN marker"
    if not ends:
        if any(line.strip() == END_MARKER for line in lines):
            return "END marker has extra whitespace"
        return "missing END marker"
    if ends[0] <= starts[0]:
        return "END marker precedes BEGIN marker"
    return "unrecognized marker layout"


def missing_begin_layout_details(text: str) -> str:
    """Add safe structural hints only; never print MCP names or TOML values."""
    lines = text.splitlines()
    heads = [i for i, line in enumerate(lines)
             if line == "[mcp_servers.context7]"]
    ends = [i for i, line in enumerate(lines) if line == END_MARKER]
    if len(heads) != 1 or len(ends) != 1 or ends[0] <= heads[0]:
        return ""
    other_headers = sum(
        line.startswith("[") for line in lines[heads[0] + 1:ends[0]]
    )
    try:
        data = parse_toml(text, label="Codex config")
    except Context7Error:
        return ""
    hints = []
    if context7_table(data) != MANAGED_CONTRACT:
        hints.append("Context7 contract differs")
    if other_headers:
        hints.append("other tables precede END")
    return "; " + "; ".join(hints) if hints else ""


def parse_toml(text: str, *, label: str) -> dict[str, object]:
    if not text.strip():
        return {}
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise Context7Error(f"{label} is not valid TOML: {exc}") from exc


def context7_table(data: dict[str, object]) -> object | None:
    servers = data.get("mcp_servers")
    if not isinstance(servers, dict):
        return None
    return servers.get("context7")


def has_context7(data: dict[str, object]) -> bool:
    servers = data.get("mcp_servers")
    return isinstance(servers, dict) and "context7" in servers


def without_context7(data: dict[str, object]) -> dict[str, object]:
    normalized = dict(data)
    servers = data.get("mcp_servers")
    if isinstance(servers, dict):
        normalized_servers = dict(servers)
        normalized_servers.pop("context7", None)
        if normalized_servers:
            normalized["mcp_servers"] = normalized_servers
        else:
            normalized.pop("mcp_servers", None)
    return normalized


def inspect_config(paths: Paths) -> ConfigState:
    try:
        text = read_regular_text(paths.config, max_bytes=MAX_CONFIG_BYTES)
        full_data = parse_toml(text, label="Codex config")
    except Context7Error as exc:
        return ConfigState(text="", kind="invalid", detail=str(exc))

    try:
        span = marker_span(text)
    except Context7Error as exc:
        return ConfigState(text=text, kind="markers-malformed", detail=str(exc))

    if span is None:
        if has_context7(full_data):
            return ConfigState(text=text, kind="unmanaged")
        return ConfigState(text=text, kind="absent")

    # Ownership comments are trusted only when the complete valid TOML actually
    # contains a Context7 table. This prevents marker-looking text inside a TOML
    # multiline string from being treated as Remote Dev-owned configuration.
    if not has_context7(full_data):
        return ConfigState(
            text=text,
            kind="conflict",
            span=span,
            detail="Context7 ownership markers exist without a parsed mcp_servers.context7 table",
        )

    start, end = span
    outside = text[:start] + text[end:]
    try:
        outside_data = parse_toml(outside, label="Codex config outside the managed Context7 block")
    except Context7Error as exc:
        return ConfigState(text=text, kind="invalid", span=span, detail=str(exc))
    if has_context7(outside_data):
        return ConfigState(
            text=text,
            kind="conflict",
            span=span,
            detail="an unowned Context7 configuration also exists outside the Remote Dev block",
        )

    block = text[start:end]
    if block != MANAGED_BLOCK or context7_table(full_data) != MANAGED_CONTRACT:
        return ConfigState(text=text, kind="managed-drift", span=span)
    return ConfigState(text=text, kind="managed", span=span)


def fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise Context7Error(f"refusing to replace non-regular or symlinked file: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        os.chmod(path, mode)
        fsync_directory(path.parent)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def locked_codex_config(paths: Paths):
    """Serialize Context7 transactions with Playwright's Codex config writer.

    Browser provisioning flocks the CODEX_HOME directory inode before reading,
    checking, and replacing config.toml. Hold that same flock from the
    Context7 snapshot through its backup and atomic replacement, with the
    same bounded nonblocking wait used by the browser.
    """
    validate_home(paths, create=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(paths.home, flags)
    except OSError as exc:
        raise Context7Error("could not lock the Codex config directory") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise Context7Error("unsafe Codex config directory permissions")
        deadline = time.monotonic() + CONFIG_LOCK_WAIT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise Context7Error("Codex configuration lock busy; retry") from exc
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        yield
    finally:
        os.close(fd)


def backup_and_replace_config(paths: Paths, old: str, new: str) -> bool:
    # Called only while holding locked_codex_config. Fail closed if an
    # external writer changed the snapshot despite the advisory flock.
    if read_regular_text(paths.config, max_bytes=MAX_CONFIG_BYTES) != old:
        raise Context7Error("Codex config changed during the Context7 update; retry")
    if old == new:
        if paths.config.exists():
            os.chmod(paths.config, 0o600)
        return False
    validate_home(paths, create=True)
    if paths.config.exists():
        backup = paths.backup
        # Preserve the *first* rollback snapshot across later reinstalls.
        # Every subsequent changed preimage gets a new private backup.
        if backup.exists() or backup.is_symlink():
            info = backup.lstat()
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.geteuid()
                    or (stat.S_IMODE(info.st_mode) & 0o077)):
                raise Context7Error("unsafe existing Context7 rollback backup")
            backup = backup.with_name(backup.name + "." + secrets.token_hex(8))
        atomic_write(backup, old, mode=0o600)
    atomic_write(paths.config, new, mode=0o600)
    return True


def append_managed_block(text: str) -> str:
    if not text:
        return MANAGED_BLOCK
    if text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    return text + separator + MANAGED_BLOCK


def safe_missing_begin_candidate(state: ConfigState) -> str | None:
    """Reclaim only a byte-for-byte intact managed block missing BEGIN.

    Never guess ownership from a partial table. The missing-BEGIN case is
    admitted only if the whole expected managed block (except its first
    comment line) occurs exactly once, contains the expected Context7 MCP
    contract and adding that one comment restores 'managed' status.
    """
    if (state.kind != "markers-malformed"
            or marker_layout_reason(state.text) != "missing BEGIN marker"):
        return None
    suffix = MANAGED_BLOCK[len(START_MARKER) + 1:]
    if state.text.count(suffix) != 1:
        return None
    try:
        original = parse_toml(state.text, label="Codex config")
    except Context7Error:
        return None
    if context7_table(original) != MANAGED_CONTRACT:
        return None
    at = state.text.index(suffix)
    candidate = state.text[:at] + START_MARKER + "\n" + state.text[at:]
    if inspect_config_candidate(candidate) != "managed":
        return None
    return candidate


def safe_interleaved_legacy_candidate(state: ConfigState) -> str | None:
    """Recover a narrowly recognized legacy Context7 block on explicit repair.

    A missing BEGIN and a displaced END may surround other MCP tables.
    Never claim the intervening tables as managed Context7. Only accept the
    exact reviewed two-field legacy Context7 table and rebuild it with
    enabled=true / required=false. All unrelated TOML must remain unchanged.
    """
    if (state.kind != "markers-malformed"
            or marker_layout_reason(state.text) != "missing BEGIN marker"):
        return None

    lines = state.text.splitlines(keepends=True)
    ctx_indices = [i for i, line in enumerate(lines)
                   if line == "[mcp_servers.context7]\n"]
    end_indices = [i for i, line in enumerate(lines)
                   if line == END_MARKER + "\n"]
    if len(ctx_indices) != 1 or len(end_indices) != 1:
        return None
    start, old_end = ctx_indices[0], end_indices[0]
    if old_end <= start:
        return None
    later_headers = [
        i for i in range(start + 1, old_end)
        if lines[i].startswith("[") and lines[i].rstrip("\r\n").endswith("]")
    ]
    if not later_headers or any(
        not lines[i].startswith("[mcp_servers.")
        for i in later_headers
    ):
        return None
    first_other = later_headers[0]
    expected_legacy = [
        "[mcp_servers.context7]\n",
        f'url = "{CONTEXT7_ENDPOINT}"\n',
        f'env_http_headers = {{ "CONTEXT7_API_KEY" = "{CONTEXT7_ENV}" }}\n',
    ]
    if lines[start:start + 3] != expected_legacy:
        return None
    # Forbid extra Context7 fields or comments that might express an
    # intentional user setting. Only blank lines may separate MCP tables.
    if any(line.strip() for line in lines[start + 3:first_other]):
        return None
    try:
        before = parse_toml(state.text, label="Codex config")
    except Context7Error:
        return None
    table = context7_table(before)
    if (not isinstance(table, dict)
            or set(table) != {"url", "env_http_headers"}
            or table["url"] != MANAGED_CONTRACT["url"]
            or table["env_http_headers"] != MANAGED_CONTRACT["env_http_headers"]):
        return None

    # Replace only the two-field Context7 table at its original location,
    # remove the displaced END comment, leave the other MCP tables byte-exact.
    candidate = (
        "".join(lines[:start])
        + MANAGED_BLOCK
        + "".join(lines[start + 3:old_end])
        + "".join(lines[old_end + 1:])
    )
    try:
        after = parse_toml(candidate, label="recovered Codex config")
    except Context7Error:
        return None
    if (context7_table(after) != MANAGED_CONTRACT
            or without_context7(before) != without_context7(after)
            or inspect_config_candidate(candidate) != "managed"):
        return None
    return candidate


def safe_nested_headers_legacy_candidate(state: ConfigState) -> str | None:
    """Recognize the exact hosted Context7 legacy *subtable* syntax.

    Old Codex MCP registration may use [mcp_servers.context7.env_http_headers]
    rather than the managed inline-header table. Rebuilding Context7 requires
    semantic equality of its two known fields, no user customization, a single
    displaced END marker, and unchanged semantics for every other MCP.
    """
    if (state.kind != "markers-malformed"
            or marker_layout_reason(state.text) != "missing BEGIN marker"):
        return None
    lines = state.text.splitlines(keepends=True)
    ctx_header = "[mcp_servers.context7]\n"
    nested_header = "[mcp_servers.context7.env_http_headers]\n"
    ctx = [i for i, line in enumerate(lines) if line == ctx_header]
    ends = [i for i, line in enumerate(lines) if line == END_MARKER + "\n"]
    if len(ctx) != 1 or len(ends) != 1 or ctx[0] >= ends[0]:
        return None
    start, old_end = ctx[0], ends[0]
    headers = [
        (i, lines[i].rstrip("\r\n"))
        for i in range(start + 1, old_end)
        if lines[i].startswith("[") and lines[i].rstrip("\r\n").endswith("]")
    ]
    if len(headers) < 2 or headers[0][1] != nested_header.rstrip("\n"):
        return None
    nested = headers[0][0]
    first_other = headers[1][0]
    if any(
        not header.startswith("[mcp_servers.")
        or header.startswith("[mcp_servers.context7.")
        or header == "[mcp_servers.context7]"
        for _, header in headers[1:]
    ):
        return None
    url_line = f'url = "{CONTEXT7_ENDPOINT}"\n'
    url_fields = [line for line in lines[start + 1:nested] if line.strip()]
    if url_fields != [url_line]:
        return None
    key_fields = [
        (i, line) for i, line in enumerate(lines[nested + 1:first_other], nested + 1)
        if line.strip()
    ]
    accepted_keys = {
        f'{CONTEXT7_ENV} = "{CONTEXT7_ENV}"\n',
        f'"{CONTEXT7_ENV}" = "{CONTEXT7_ENV}"\n',
    }
    if len(key_fields) != 1 or key_fields[0][1] not in accepted_keys:
        return None
    try:
        before = parse_toml(state.text, label="Codex config")
    except Context7Error:
        return None
    table = context7_table(before)
    if (not isinstance(table, dict)
            or set(table) != {"url", "env_http_headers"}
            or table["url"] != MANAGED_CONTRACT["url"]
            or table["env_http_headers"] != MANAGED_CONTRACT["env_http_headers"]):
        return None

    # Preserve the *exact* bytes following the known header mapping, including
    # inter-table spacing and every unrelated MCP table. Only the misplaced END
    # comment and the known two-field Context7 stanza are removed.
    end_of_key = key_fields[0][0] + 1
    candidate = (
        "".join(lines[:start]) + MANAGED_BLOCK
        + "".join(lines[end_of_key:old_end])
        + "".join(lines[old_end + 1:])
    )
    try:
        after = parse_toml(candidate, label="reconstructed Codex config")
    except Context7Error:
        return None
    if (context7_table(after) != MANAGED_CONTRACT
            or without_context7(before) != without_context7(after)
            or inspect_config_candidate(candidate) != "managed"):
        return None
    return candidate


def recognized_legacy_recovery(state: ConfigState) -> str | None:
    """Only these three reviewed layouts may be reconstructed."""
    return (
        safe_missing_begin_candidate(state)
        or safe_interleaved_legacy_candidate(state)
        or safe_nested_headers_legacy_candidate(state)
    )


def scoped_reinstall_candidate(state: ConfigState) -> str | None:
    """Reinstall the *entire* Context7 MCP registration, not its legacy fields.

    Syntax-aware at TOML table boundaries. Preserve all unrelated input bytes
    except a unique orphaned Remote Dev END marker. Reset only Context7's own
    parent/child TOML tables. An ambiguous scope fails closed.
    """
    if state.kind in {"invalid", "conflict"}:
        return None
    if state.kind == "managed":
        return state.text
    if state.kind == "absent":
        # A valid pre-existing inline mcp_servers table cannot be extended
        # with a regular TOML child header. Validate the entire proposal and
        # prove unrelated configuration is unchanged before allowing writes.
        candidate = append_managed_block(state.text)
        try:
            before = parse_toml(state.text, label="existing Codex config")
            after = parse_toml(candidate, label="proposed Context7 install")
        except Context7Error:
            return None
        if (context7_table(after) != MANAGED_CONTRACT
                or without_context7(before) != without_context7(after)
                or inspect_config_candidate(candidate) != "managed"):
            return None
        return candidate
    try:
        before = parse_toml(state.text, label="Codex MCP config")
    except Context7Error:
        return None
    if not isinstance(context7_table(before), dict):
        return None
    lines = state.text.splitlines(keepends=True)
    roots = [i for i, line in enumerate(lines)
             if line.rstrip("\r\n") == "[mcp_servers.context7]"]
    if len(roots) != 1:
        return None
    start = roots[0]
    starts = [i for i, line in enumerate(lines)
              if line.rstrip("\r\n") == START_MARKER]
    ends = [i for i, line in enumerate(lines)
            if line.rstrip("\r\n") == END_MARKER]
    if len(starts) > 1 or len(ends) > 1:
        return None
    if starts and (starts[0] != start - 1):
        return None
    if ends and ends[0] < start:
        return None

    # Context7 child tables can follow its root. Stop at the next unrelated
    # TOML table, preserving everything beginning at that table verbatim.
    after = len(lines)
    foreign_seen = False
    for i in range(start + 1, len(lines)):
        header = lines[i].strip()
        if not (header.startswith("[") and header.endswith("]")):
            continue
        if header.startswith("[mcp_servers.context7."):
            if foreign_seen:
                return None
            continue
        foreign_seen = True
        if after == len(lines):
            after = i
    if ends and ends[0] >= start and ends[0] < after:
        # The old END is part of the Context7 stanza, and is removed with it.
        pass
    keep = set(range(start, after))
    if starts:
        keep.add(starts[0])
    if ends:
        keep.add(ends[0])
    pieces = []
    for i, line in enumerate(lines):
        if i == start:
            pieces.append(MANAGED_BLOCK)
        if i not in keep:
            pieces.append(line)
    candidate = "".join(pieces)
    try:
        rebuilt = parse_toml(candidate, label="reinstalled MCP config")
        if (context7_table(rebuilt) != MANAGED_CONTRACT
                or without_context7(before) != without_context7(rebuilt)
                or inspect_config_candidate(candidate) != "managed"):
            return None
    except Context7Error:
        return None
    return candidate


def inspect_config_candidate(text: str) -> str:
    """Validate a proposed repair without reading or writing private files."""
    try:
        span = marker_span(text)
        data = parse_toml(text, label="repaired Codex config")
        if span is None or context7_table(data) != MANAGED_CONTRACT:
            return "invalid"
        start, end = span
        if text[start:end] != MANAGED_BLOCK:
            return "invalid"
        outside = parse_toml(text[:start] + text[end:],
                             label="repaired Codex config outside Context7")
        if has_context7(outside):
            return "invalid"
    except Context7Error:
        return "invalid"
    return "managed"


def managed_candidate(
    state: ConfigState, *, require_existing: bool,
    allow_legacy_recovery: bool = False,
) -> str:
    if state.kind == "unmanaged":
        raise Context7Error(
            "an unowned [mcp_servers.context7] entry already exists; Remote Dev will not overwrite it"
        )
    if state.kind == "markers-malformed":
        if not allow_legacy_recovery:
            raise Context7Error(
                "malformed Context7 ownership markers require explicit install/repair --yes"
            )
        candidate = recognized_legacy_recovery(state)
        if candidate is None:
            raise Context7Error("malformed Context7 ownership markers require manual review")
        return candidate
    if state.kind in {"invalid", "conflict"}:
        raise Context7Error(state.detail or f"cannot safely modify Context7 state: {state.kind}")
    if require_existing and state.kind == "absent":
        raise Context7Error("Context7 is not managed by Remote Dev; use install first")

    if state.span is None:
        candidate = append_managed_block(state.text)
    else:
        start, end = state.span
        candidate = state.text[:start] + MANAGED_BLOCK + state.text[end:]

    data = parse_toml(candidate, label="resulting Codex config")
    if context7_table(data) != MANAGED_CONTRACT:
        raise Context7Error("resulting Context7 configuration does not match the reviewed contract")
    return candidate


def ensure_state_dir(paths: Paths) -> None:
    validate_home(paths, create=True)
    if paths.state_dir.exists() or paths.state_dir.is_symlink():
        info = paths.state_dir.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Context7Error(f"Context7 state path must be a real directory: {paths.state_dir}")
        if info.st_uid != os.geteuid():
            raise Context7Error("Context7 state directory is not owned by the service user")
    else:
        paths.state_dir.mkdir(mode=0o700)
    os.chmod(paths.state_dir, 0o700)


def validate_api_key(value: str) -> str:
    if not value or len(value.encode("utf-8")) > MAX_KEY_BYTES:
        raise Context7Error("Context7 API key is empty or exceeds the supported size limit")
    if value != value.strip() or any(character.isspace() for character in value):
        raise Context7Error("Context7 API key must not contain whitespace or line breaks")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise Context7Error("Context7 API key contains control characters")
    return value


def read_private_key_from_fd(fd: int) -> str:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        raise Context7Error("Context7 API-key path is not a regular file")
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise Context7Error("Context7 API-key file ownership or permissions are unsafe")
    if info.st_size <= 0 or info.st_size > MAX_KEY_BYTES:
        raise Context7Error("Context7 API-key file size is unsafe")

    chunks: list[bytes] = []
    remaining = MAX_KEY_BYTES + 1
    while remaining > 0:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if not data or len(data) > MAX_KEY_BYTES:
        raise Context7Error("Context7 API-key file size is unsafe")
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Context7Error("Context7 API-key file is not valid UTF-8") from exc
    return validate_api_key(value)


def secret_status(paths: Paths) -> tuple[str, str | None]:
    state_fd: int | None = None
    key_fd: int | None = None
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    # O_NONBLOCK prevents a FIFO path without a writer from hanging status/plan.
    # read_private_key_from_fd still rejects non-regular descriptors.
    key_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        try:
            state_fd = os.open(paths.state_dir, directory_flags)
        except FileNotFoundError:
            return "missing", None
        state_info = os.fstat(state_fd)
        if not stat.S_ISDIR(state_info.st_mode):
            return "unsafe", None
        if state_info.st_uid != os.geteuid() or stat.S_IMODE(state_info.st_mode) & 0o077:
            return "unsafe", None

        try:
            key_fd = os.open("api-key", key_flags, dir_fd=state_fd)
        except FileNotFoundError:
            return "missing", None
        value = read_private_key_from_fd(key_fd)
    except (OSError, UnicodeDecodeError, Context7Error):
        return "unsafe", None
    finally:
        if key_fd is not None:
            os.close(key_fd)
        if state_fd is not None:
            os.close(state_fd)
    return "safe", value


def store_key(paths: Paths, value: str) -> None:
    ensure_state_dir(paths)
    atomic_write(paths.key, validate_api_key(value), mode=0o600)


def remove_owned_key(paths: Paths) -> None:
    if not paths.state_dir.exists() and not paths.state_dir.is_symlink():
        return
    info = paths.state_dir.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise Context7Error(f"refusing unsafe Context7 state path: {paths.state_dir}")
    if info.st_uid != os.geteuid():
        raise Context7Error("refusing Context7 state not owned by the service user")
    if paths.key.exists() or paths.key.is_symlink():
        paths.key.unlink()
        fsync_directory(paths.state_dir)
    try:
        paths.state_dir.rmdir()
    except OSError:
        pass


def confirm(action: str, *, yes: bool, network: bool = False) -> None:
    if yes:
        return
    if not sys.stdin.isatty():
        raise Context7Error(f"{action} requires interactive confirmation or --yes")
    print(
        "Context7 is an optional external service operated by Upstash. "
        "MCP-generated documentation queries may be sent to that service; do not send sensitive or regulated data.",
        file=sys.stderr,
    )
    if network:
        print("This action performs an explicit network connection test.", file=sys.stderr)
    answer = input(f"{action} Context7 integration? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        raise Context7Error("cancelled")


def read_key_from_stdin() -> str:
    data = sys.stdin.buffer.read(MAX_KEY_BYTES + 1)
    if len(data) > MAX_KEY_BYTES:
        raise Context7Error("Context7 API key exceeds the supported size limit")
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Context7Error("Context7 API key must be valid UTF-8") from exc
    if value.endswith("\n"):
        value = value[:-1]
    return validate_api_key(value)


def choose_key(paths: Paths, args: argparse.Namespace) -> tuple[str, str | None]:
    current_status, current_value = secret_status(paths)
    if current_status == "unsafe":
        raise Context7Error("existing Context7 API-key state is unsafe; remove or repair its permissions first")
    if args.anonymous:
        return "anonymous", None
    if args.api_key_stdin:
        if not args.yes:
            raise Context7Error("--api-key-stdin requires --yes so stdin is reserved for the API key")
        return "replace", read_key_from_stdin()
    if sys.stdin.isatty() and not args.yes:
        prompt = "Context7 API key (optional; blank keeps the current key or uses anonymous access): "
        entered = getpass.getpass(prompt, echo_char="*")
        if entered:
            return "replace", validate_api_key(entered)
    if current_status == "safe":
        return "keep", current_value
    return "anonymous", None


def apply_managed_config(
    paths: Paths, *, require_existing: bool,
    allow_legacy_recovery: bool = False,
) -> bool:
    with locked_codex_config(paths):
        state = inspect_config(paths)
        candidate = managed_candidate(
            state, require_existing=require_existing,
            allow_legacy_recovery=allow_legacy_recovery,
        )
        return backup_and_replace_config(paths, state.text, candidate)


def command_install(paths: Paths, args: argparse.Namespace) -> int:
    confirm("Install/repair", yes=args.yes)
    key_action, key_value = choose_key(paths, args)
    if key_action == "replace":
        ensure_state_dir(paths)
    changed = apply_managed_config(
        paths, require_existing=False, allow_legacy_recovery=args.yes,
    )
    if key_action == "replace" and key_value is not None:
        store_key(paths, key_value)
    elif key_action == "anonymous":
        remove_owned_key(paths)
    print("Context7 managed configuration: installed" if changed else "Context7 managed configuration: already current")
    status, _ = secret_status(paths)
    print("Context7 authentication: API key stored privately" if status == "safe" else "Context7 authentication: anonymous")
    return 0


def command_reinstall(paths: Paths, args: argparse.Namespace) -> int:
    """Explicitly replace *only* Context7's MCP registration; retain key."""
    confirm("Reinstall only Context7 MCP (reset custom Context7 settings)", yes=args.yes)
    with locked_codex_config(paths):
        state = inspect_config(paths)
        auth, _ = secret_status(paths)
        if auth == "unsafe":
            raise Context7Error("Context7 authentication state is unsafe; reinstall blocked")
        candidate = scoped_reinstall_candidate(state)
        if candidate is None:
            raise Context7Error("Context7 registration cannot be isolated safely; no changes made")
        changed = backup_and_replace_config(paths, state.text, candidate)
    print("Context7 MCP: reinstalled" if changed else "Context7 MCP: already current")
    print("Context7 API key: preserved (no credential changes)")
    return 0


def command_update(paths: Paths, args: argparse.Namespace) -> int:
    confirm("Update/reapply", yes=args.yes)
    changed = apply_managed_config(
        paths, require_existing=True, allow_legacy_recovery=False,
    )
    print("Context7 managed configuration: updated" if changed else "Context7 managed configuration: already current")
    print("Context7 update network: not used (hosted MCP contract only)")
    return 0


def remove_managed_block(paths: Paths) -> bool:
    with locked_codex_config(paths):
        state = inspect_config(paths)
        if state.kind == "unmanaged":
            raise Context7Error(
                "an unowned [mcp_servers.context7] entry exists; Remote Dev will not remove it"
            )
        if state.kind in {"markers-malformed", "invalid", "conflict"}:
            raise Context7Error(state.detail or f"cannot safely remove Context7 state: {state.kind}")
        if state.span is None:
            return False
        start, end = state.span
        candidate = state.text[:start] + state.text[end:]
        before = parse_toml(state.text, label="Codex config before Context7 removal")
        result = parse_toml(candidate, label="Codex config after Context7 removal")
        if has_context7(result):
            raise Context7Error("Context7 configuration survives removal; refusing to rewrite the Codex config")
        if without_context7(before) != without_context7(result):
            raise Context7Error(
                "removing the managed Context7 block would change unrelated Codex configuration; resolve the drift manually"
            )
        return backup_and_replace_config(paths, state.text, candidate)


def command_remove(paths: Paths, args: argparse.Namespace) -> int:
    confirm("Remove", yes=args.yes)
    changed = remove_managed_block(paths)
    remove_owned_key(paths)
    print("Context7 managed configuration: removed" if changed else "Context7 managed configuration: not present")
    print("Unowned Codex configuration was not modified.")
    return 0


def status_line(paths: Paths) -> tuple[str, int]:
    state = inspect_config(paths)
    if state.kind == "absent":
        return "Context7: not configured", 0
    if state.kind == "unmanaged":
        return "Context7: unmanaged configuration (Remote Dev will not modify)", 0
    if state.kind != "managed":
        # Only print stable diagnostic categories. state.detail may contain
        # untrusted TOML or local path details, so never emit it in Doctor.
        if state.kind == "markers-malformed":
            subtype = marker_layout_reason(state.text)
            reason = ("Context7 ownership markers malformed: " + subtype)
            if subtype == "missing BEGIN marker":
                reason += missing_begin_layout_details(state.text)
        else:
            reason = {
                "invalid": "Codex config unreadable or invalid",
                "conflict": "Context7 ownership conflict",
                "managed-drift": "managed Context7 contract drift",
            }.get(state.kind, "unrecognized Context7 configuration state")
        # The same verified scope check drives the menu/Doctor recommendation
        # for all damaged states, not just one historical marker layout.
        if (scoped_reinstall_candidate(state) is not None
                and secret_status(paths)[0] != "unsafe"):
            reason += "; reinstall Context7 via menu or reinstall --yes"
        else:
            reason += "; no verified scoped reinstall; manual review required"
        return (
            "Context7: managed configuration damaged or Codex config invalid "
            f"({reason})",
            3,
        )
    secret, _ = secret_status(paths)
    if secret == "safe":
        return "Context7: configured (API key stored)", 0
    if secret == "missing":
        return "Context7: configured (anonymous)", 0
    return "Context7: configured but API-key state is unsafe", 3


def command_plan(paths: Paths, _args: argparse.Namespace) -> int:
    """Passive/offline eligibility preview; never modifies config or keys."""
    state = inspect_config(paths)
    auth, _ = secret_status(paths)
    if auth == "unsafe":
        print("Context7 recovery: BLOCKED (private authentication state unsafe)")
        return 3
    if state.kind == "managed":
        print("Context7 recovery: ALREADY MANAGED (nothing to reinstall)")
        return 0
    if state.kind == "absent":
        if scoped_reinstall_candidate(state) is None:
            print("Context7 recovery: BLOCKED (existing MCP format prevents safe install)")
            return 3
        print("Context7 recovery: NOT INSTALLED (safe Context7 registration available)")
        print("Action: remote-dev-context7 reinstall --yes")
        return 0
    if scoped_reinstall_candidate(state) is not None:
        print("Context7 recovery: REINSTALLABLE (read-only scope verification)")
        print("Action: remote-dev-context7 reinstall --yes")
        print("Effect: reset Context7's registration only; customized Context7 fields are discarded")
        print("Safety: original config backed up; unrelated MCPs and private API key preserved")
        return 0
    print("Context7 recovery: BLOCKED (unsupported or ambiguous ownership layout)")
    print("Action: manual review; do not remove/reinstall other MCP entries")
    return 3


def command_status(paths: Paths, args: argparse.Namespace) -> int:
    line, code = status_line(paths)
    print(line)
    if not args.menu:
        print(f"Endpoint: {CONTEXT7_ENDPOINT}")
        print("Required for Codex startup: no")
        print("Passive status network: not used")
        print("Service operator: Upstash (external to Remote Dev/OpenAI)")
    return code


def validate_codex_mcp_get(output: str) -> None:
    try:
        entry = json.loads(output)
    except json.JSONDecodeError as exc:
        raise Context7Error("bundled Codex returned invalid JSON for the Context7 MCP server") from exc
    if not isinstance(entry, dict) or entry.get("name") != "context7":
        raise Context7Error("bundled Codex returned an unexpected Context7 MCP server shape")

    transport = entry.get("transport")
    if (
        entry.get("enabled") is not True
        or not isinstance(transport, dict)
        or transport.get("type") != "streamable_http"
        or transport.get("url") != CONTEXT7_ENDPOINT
        or transport.get("bearer_token_env_var") is not None
        or transport.get("http_headers") is not None
        or transport.get("env_http_headers") != {"CONTEXT7_API_KEY": CONTEXT7_ENV}
    ):
        raise Context7Error("bundled Codex reported an unexpected managed Context7 server contract")


def bundled_codex_accepts_config(paths: Paths) -> None:
    if not BUNDLED_CODEX.is_file() or not os.access(BUNDLED_CODEX, os.X_OK):
        raise Context7Error(f"bundled Codex executable is unavailable: {BUNDLED_CODEX}")
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(paths.home)
    secret, value = secret_status(paths)
    if secret == "safe" and value is not None:
        environment[CONTEXT7_ENV] = value
    else:
        environment.pop(CONTEXT7_ENV, None)
    try:
        # `mcp get` reads and serializes one configured server without the
        # authentication discovery performed by `mcp list`, so this contract
        # check remains local. Network belongs only to the explicit ping below.
        result = subprocess.run(
            [str(BUNDLED_CODEX), "mcp", "get", "context7", "--json"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Context7Error(f"could not validate config with bundled Codex: {type(exc).__name__}") from exc
    if result.returncode != 0:
        raise Context7Error(f"bundled Codex rejected the MCP configuration (exit {result.returncode})")
    validate_codex_mcp_get(result.stdout)


def hosted_ping() -> None:
    request = Request(
        CONTEXT7_PING,
        headers={"User-Agent": "remote-dev-context7/0.1"},
        method="GET",
    )
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=10) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "mcp.context7.com" or final.path != "/ping":
                raise Context7Error("Context7 ping response came from an unexpected endpoint")
            payload = response.read(MAX_PING_BYTES + 1)
            if len(payload) > MAX_PING_BYTES:
                raise Context7Error("Context7 ping response exceeded the supported size limit")
    except Context7Error:
        raise
    except Exception as exc:
        raise Context7Error(f"Context7 hosted endpoint is unreachable: {type(exc).__name__}") from exc
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Context7Error("Context7 ping returned an unexpected response") from exc
    if not isinstance(data, dict):
        raise Context7Error("Context7 ping returned an unexpected response")
    if data.get("status") != "ok" or data.get("message") != "pong":
        raise Context7Error("Context7 ping returned an unexpected status")


def command_test(paths: Paths, args: argparse.Namespace) -> int:
    confirm("Test", yes=args.yes, network=True)
    state = inspect_config(paths)
    if state.kind != "managed":
        raise Context7Error("Context7 must have a healthy Remote Dev-managed configuration before testing")
    secret, _ = secret_status(paths)
    if secret == "unsafe":
        raise Context7Error("Context7 API-key state is unsafe")
    bundled_codex_accepts_config(paths)
    print("Bundled Codex MCP configuration: OK")
    hosted_ping()
    print("Context7 hosted endpoint: OK")
    return 0


def command_key_file(paths: Paths, args: argparse.Namespace) -> int:
    if not args.active:
        raise Context7Error("key-file is an internal command and requires --active")
    state = inspect_config(paths)
    if state.kind != "managed":
        return 4 if state.kind in {"absent", "unmanaged"} else 3
    secret, _ = secret_status(paths)
    if secret == "missing":
        return 5
    if secret != "safe":
        return 3
    print(paths.key)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="remote-dev-context7",
        description="Manage the optional hosted Context7 MCP integration for the Codex service.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--menu", action="store_true")

    subparsers.add_parser("plan", help="Read-only Context7 recovery eligibility preview")

    for name in ("install", "repair"):
        action = subparsers.add_parser(name)
        action.add_argument("--yes", action="store_true")
        auth = action.add_mutually_exclusive_group()
        auth.add_argument("--anonymous", action="store_true")
        auth.add_argument("--api-key-stdin", action="store_true")

    reinstall_parser = subparsers.add_parser("reinstall")
    reinstall_parser.add_argument("--yes", action="store_true")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("--yes", action="store_true")

    test_parser = subparsers.add_parser("test")
    test_parser.add_argument("--yes", action="store_true")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--yes", action="store_true")

    key_file = subparsers.add_parser("key-file", help=argparse.SUPPRESS)
    key_file.add_argument("--active", action="store_true", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        validate_role()
        paths = Paths()
        validate_home(paths, create=False)
        if args.command == "status":
            return command_status(paths, args)
        if args.command == "plan":
            return command_plan(paths, args)
        if args.command in {"install", "repair"}:
            return command_install(paths, args)
        if args.command == "update":
            return command_update(paths, args)
        if args.command == "reinstall":
            return command_reinstall(paths, args)
        if args.command == "test":
            return command_test(paths, args)
        if args.command == "remove":
            return command_remove(paths, args)
        if args.command == "key-file":
            return command_key_file(paths, args)
        parser.error(f"unsupported command: {args.command}")
    except Context7Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("ERROR: cancelled", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: local Context7 state operation failed (errno {exc.errno})", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
