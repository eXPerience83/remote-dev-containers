#!/usr/bin/env python3
"""Maintain the hosted Context7 MCP registration in Antigravity CLI.

The global JSON entry uses the vendor-documented serverUrl transport.
Do not write authentication secrets to mcp_config.json: anonymous remote
access is the default. All mutations are explicit, scoped, locked and backed up.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request

ENDPOINT = "https://mcp.context7.com/mcp"
PING = "https://mcp.context7.com/ping"
ENTRY = {"serverUrl": ENDPOINT}
CONFIG_DIR = Path("/root/.gemini/config")
CONFIG_FILE = "mcp_config.json"
BACKUP_FILE = "mcp_config.json.remote-dev-context7.bak"


class MaintenanceError(RuntimeError):
    pass


def operations():
    """Reuse the browser provider's secure dirfd, flock and atomic writers.

    This is an image-owned module, not a vendor-controlled Python dependency.
    """
    path = Path("/usr/local/bin/remote-dev-browser-config")
    if not path.is_file():
        path = Path(__file__).with_name("remote-dev-browser-config.py")
    loader = importlib.machinery.SourceFileLoader("_remote_dev_browser_config_shared", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:
        raise MaintenanceError("configuration backend unavailable")
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MaintenanceError("ambiguous duplicate JSON keys; no changes permitted")
        result[key] = value
    return result


def inspect(content: bytes):
    try:
        doc = json.loads(content.decode("utf-8"), object_pairs_hook=reject_duplicate_keys) if content.strip() else {}
    except (UnicodeError, ValueError) as exc:
        raise MaintenanceError("Antigravity MCP JSON is invalid; no changes permitted") from exc
    if not isinstance(doc, dict):
        raise MaintenanceError("Antigravity MCP root must be a JSON object")
    servers = doc.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise MaintenanceError("Antigravity MCP servers must be an object")
    if "context7" not in servers:
        return "absent", doc
    current = servers["context7"]
    if current == ENTRY:
        return "managed", doc
    if not isinstance(current, dict):
        raise MaintenanceError("Context7 entry is not a JSON object")
    # Never overwrite credentials, intentionally disabled MCPs or entries
    # with provider-specific user options. Query strings and userinfo can
    # themselves contain secrets, even without an explicit headers field.
    sensitive = {"headers", "oauth", "env", "args", "command",
                 "apikey", "token", "secret", "authprovidertype", "authorization"}
    if any(key.casefold() in sensitive or "secret" in key.casefold()
           for key in current):
        return "custom-auth", doc
    for key in ("serverUrl", "url", "httpUrl"):
        uri = current.get(key)
        if isinstance(uri, str):
            parsed_url = urlparse(uri)
            if (parsed_url.username is not None or parsed_url.password is not None
                    or parsed_url.query or parsed_url.fragment):
                return "custom-auth", doc
    if current.get("disabled") is True:
        return "custom", doc
    if current.get("serverUrl") == ENDPOINT and set(current) != set(ENTRY):
        # A working hosted registration with extra timeouts, tool filters,
        # or provider options is user-managed, not corrupted.
        return "custom", doc
    return "drift", doc


def candidate(doc: dict) -> bytes:
    updated = dict(doc)
    servers = dict(doc.get("mcpServers", {}))
    servers["context7"] = dict(ENTRY)
    updated["mcpServers"] = servers
    # JSON is reserialized canonically; every non-Context7 value is asserted
    # semantically identical. Exact original bytes remain in the backup.
    if {k: v for k, v in servers.items() if k != "context7"} != {
        k: v for k, v in doc.get("mcpServers", {}).items() if k != "context7"
    }:
        raise MaintenanceError("unrelated MCP entry would change")
    return (json.dumps(updated, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def using_config(directory: Path, mutator):
    ops = operations()
    try:
        fd = ops.validate_directory(directory)
    except (OSError, ops.UnsafeConfig) as exc:
        raise MaintenanceError("unsafe or missing Antigravity global config directory") from exc
    try:
        ops.acquire_lock(fd)
        contents, info = ops.read_config(fd, CONFIG_FILE)
        return mutator(ops, fd, contents, info)
    except (OSError, ops.UnsafeConfig) as exc:
        raise MaintenanceError("Antigravity MCP config unavailable or changed; no overwrite") from exc
    finally:
        os.close(fd)


def status(directory: Path, *, verbose: bool = False) -> int:
    try:
        state, _ = using_config(directory, lambda _ops, _fd, data, _info: inspect(data))
    except MaintenanceError:
        print("Context7 (Antigravity): unsafe or invalid MCP config; manual review required")
        return 3
    if state == "managed":
        print("Context7 (Antigravity): configured (hosted anonymous MCP)")
        return 0
    if state == "absent":
        print("Context7 (Antigravity): not installed")
        return 0
    if state in {"custom-auth", "custom"}:
        print("Context7 (Antigravity): user-managed MCP entry (left untouched)")
        return 0
    print("Context7 (Antigravity): registration differs; reinstall recommended")
    return 3


def plan(directory: Path) -> int:
    try:
        state, _ = using_config(directory, lambda _ops, _fd, data, _info: inspect(data))
    except MaintenanceError:
        print("Context7 (Antigravity): BLOCKED, invalid/unsafe configuration")
        return 3
    if state == "managed":
        print("Context7 (Antigravity): ALREADY INSTALLED, no reinstall needed")
        return 0
    if state in {"custom-auth", "custom"}:
        print("Context7 (Antigravity): BLOCKED, user-managed settings; preserve this entry")
        return 3
    print("Context7 (Antigravity): REINSTALLABLE" if state == "drift"
          else "Context7 (Antigravity): NOT INSTALLED; installation available")
    print("Action: remote-dev-context7-antigravity reinstall --yes")
    print("Effect: reset only the Context7 global MCP entry to the official hosted endpoint")
    print("Authentication: anonymous (no API key stored in JSON)")
    return 0


def reinstall(directory: Path) -> int:
    def mutate(ops, fd, content, info):
        state, doc = inspect(content)
        if state in {"custom-auth", "custom"}:
            raise MaintenanceError("user-owned Context7 settings; refusing to replace them")
        updated = candidate(doc)
        if content == updated:
            return False
        # Before any mutation, create a private exact pre-image backup.
        if info is not None:
            # Keep the first original rollback file intact. Later changed
            # configurations use unique private snapshots, not a destructive
            # rewrite of the original backup.
            prev, prev_info = ops.read_config(fd, BACKUP_FILE)
            backup_name = (BACKUP_FILE if prev_info is None
                           else BACKUP_FILE + "." + secrets.token_hex(8))
            ops.atomic_write(fd, backup_name, None, content, b"")
        ops.atomic_write(fd, CONFIG_FILE, info, updated, content)
        return True

    try:
        changed = using_config(directory, mutate)
    except MaintenanceError:
        print("Context7 (Antigravity): reinstall BLOCKED; global MCP config left untouched")
        return 3
    print("Context7 (Antigravity): installed (hosted anonymous)" if changed
          else "Context7 (Antigravity): already current")
    print("Other MCP entries: retained; original JSON backed up before replacement")
    return 0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MaintenanceError("Context7 ping redirect denied")


def test(directory: Path) -> int:
    code = status(directory)
    if code != 0:
        return 3
    state, _ = using_config(directory, lambda _ops, _fd, data, _info: inspect(data))
    if state != "managed":
        print("Context7 (Antigravity): must install first")
        return 3
    try:
        with build_opener(NoRedirect()).open(Request(PING), timeout=10) as response:
            url = urlparse(response.geturl())
            if (url.scheme, url.hostname, url.path) != ("https", "mcp.context7.com", "/ping"):
                raise MaintenanceError("unexpected ping target")
            body = response.read(4097)
            if len(body) > 4096:
                raise MaintenanceError("ping oversized")
        if json.loads(body) != {"status": "ok", "message": "pong"}:
            raise MaintenanceError("unexpected ping response")
    except (OSError, ValueError, MaintenanceError):
        print("Context7 (Antigravity): hosted endpoint test failed")
        return 3
    print("Context7 (Antigravity): hosted ping OK; confirm actual tools via agy /mcp")
    return 0


def main(argv=None, *, directory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status")
    st.add_argument("--menu", action="store_true")
    sub.add_parser("plan")
    reinstall_parser = sub.add_parser("reinstall")
    reinstall_parser.add_argument("--yes", action="store_true")
    test_parser = sub.add_parser("test")
    test_parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("REMOTE_DEV_ROLE", "antigravity") != "antigravity":
        print("Context7 (Antigravity): wrong container role", file=sys.stderr)
        return 2
    target = CONFIG_DIR if directory is None else directory
    if args.command == "status":
        return status(target)
    if args.command == "plan":
        return plan(target)
    if not args.yes:
        if not sys.stdin.isatty():
            print("Context7 (Antigravity): explicit confirmation required (--yes)", file=sys.stderr)
            return 2
        action = "REINSTALL" if args.command == "reinstall" else "TEST"
        answer = input(f"Type {action} to confirm {args.command}: ")
        if answer != action:
            print("Context7 (Antigravity): cancelled", file=sys.stderr)
            return 2
    return reinstall(target) if args.command == "reinstall" else test(target)


if __name__ == "__main__":
    raise SystemExit(main())
