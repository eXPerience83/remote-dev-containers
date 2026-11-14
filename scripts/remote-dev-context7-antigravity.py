#!/usr/bin/env python3
"""Maintain the hosted Context7 MCP registration in Antigravity CLI.

The global JSON entry uses the vendor-documented serverUrl transport.
Do not write authentication secrets to mcp_config.json: anonymous remote
access is the initial registration mode; the vendor may subsequently manage
OAuth outside this JSON. All mutations are explicit, scoped, locked and backed up.
"""
from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import math
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


def reject_nonfinite(_value: str):
    raise MaintenanceError("non-standard JSON numeric value; no changes permitted")


def parse_finite_float(value: str) -> float:
    # Python's default json.loads() silently converts 1e400 to infinity.
    result = float(value)
    if not math.isfinite(result):
        raise MaintenanceError("JSON numeric overflow; no changes permitted")
    return result


def inspect(content: bytes):
    try:
        doc = (
            json.loads(content.decode("utf-8"),
                       object_pairs_hook=reject_duplicate_keys,
                       parse_constant=reject_nonfinite,
                       parse_float=parse_finite_float)
            if content.strip() else {}
        )
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
    if any(key.casefold() in sensitive
           or "secret" in key.casefold()
           or "token" in key.casefold()
           for key in current):
        return "custom-auth", doc
    for key in ("serverUrl", "url", "httpUrl"):
        uri = current.get(key)
        if isinstance(uri, str):
            try:
                parsed_url = urlparse(uri)
                has_userinfo = (parsed_url.username is not None
                                or parsed_url.password is not None)
            except ValueError:
                # Malformed URL/userinfo must not produce a traceback or
                # accidentally authorize a destructive reinstall.
                return "custom-auth", doc
            if has_userinfo or parsed_url.query or parsed_url.fragment:
                return "custom-auth", doc
    # Only simple registrations with exactly one endpoint selector are
    # candidates for resetting. Every extra field, even on a stale URL, may
    # encode a user-owned tool restriction, timeout, or authentication policy.
    selectors = ("serverUrl", "url", "httpUrl")
    present = [key for key in selectors if key in current]
    if len(present) != 1 or set(current) != {present[0]}:
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
    try:
        encoded = json.dumps(updated, indent=2, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MaintenanceError("proposed MCP JSON is not safely serializable") from exc
    return (encoded + "\n").encode("utf-8")


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


def menu_state(directory: Path) -> int:
    """Offline, credential-free state for the interactive menu."""
    if not directory.exists() and not directory.is_symlink():
        print("blocked")  # A missing vendor mount must not be created.
        return 0
    try:
        state, _ = using_config(directory, lambda _ops, _fd, data, _info: inspect(data))
    except MaintenanceError:
        print("blocked")
        return 0
    print({"managed": "healthy", "absent": "absent", "drift": "repairable"}.get(state, "blocked"))
    return 0


def status(directory: Path) -> int:
    if not directory.exists() and not directory.is_symlink():
        # Missing optional MCP config must not make agent Doctor fail.
        # Do not create the provider-private directory from a passive probe.
        print("Context7 (Antigravity): not installed (global MCP config unavailable)")
        return 0
    try:
        state, _ = using_config(directory, lambda _ops, _fd, data, _info: inspect(data))
    except MaintenanceError:
        print("Context7 (Antigravity): unsafe or invalid MCP config; manual review required")
        return 3
    if state == "managed":
        print("Context7 (Antigravity): registration configured; authentication managed by Antigravity (/mcp), not verified")
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
    if not directory.exists() and not directory.is_symlink():
        print("Context7 (Antigravity): BLOCKED (global MCP directory missing)")
        print("Action: restore the role-private mount; do not create arbitrary vendor state")
        return 3
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
    print("Authentication: managed by Antigravity (/mcp); not inspected; no API key written to JSON")
    return 0


def reinstall(directory: Path) -> int:
    def mutate(ops, fd, content, info):
        state, doc = inspect(content)
        if state in {"custom-auth", "custom"}:
            raise MaintenanceError("user-owned Context7 settings; refusing to replace them")
        if state == "managed":
            # An already-correct entry is a true no-op; do not reformat
            # unrelated MCP JSON merely because an operator used reinstall.
            return False
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
    print("Context7 (Antigravity): registration installed" if changed
          else "Context7 (Antigravity): already current")
    print("Other MCP entries: retained; original JSON backed up before replacement")
    return 0


def remove(directory: Path) -> int:
    """Remove only the exact Remote Dev-owned Context7 registration."""
    def mutate(ops, fd, content, info):
        state, doc = inspect(content)
        if state == "absent":
            return False
        if state != "managed":
            raise MaintenanceError("custom or damaged Context7 registration; removal blocked")
        servers = dict(doc["mcpServers"])
        del servers["context7"]
        updated = dict(doc)
        updated["mcpServers"] = servers
        encoded = (json.dumps(updated, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if {k: v for k, v in updated.items() if k != "mcpServers"} != {
                k: v for k, v in doc.items() if k != "mcpServers"}:
            raise MaintenanceError("unrelated JSON settings would change")
        if info is not None:
            _, previous_backup = ops.read_config(fd, BACKUP_FILE)
            backup_name = (BACKUP_FILE if previous_backup is None
                           else BACKUP_FILE + "." + secrets.token_hex(8))
            ops.atomic_write(fd, backup_name, None, content, b"")
        ops.atomic_write(fd, CONFIG_FILE, info, encoded, content)
        return True

    try:
        changed = using_config(directory, mutate)
    except MaintenanceError:
        print("Context7 (Antigravity): removal BLOCKED; configuration preserved")
        return 3
    print("Context7 (Antigravity): registration removed" if changed
          else "Context7 (Antigravity): registration already absent")
    print("Other MCPs preserved. Antigravity OAuth session is NOT signed out or revoked.")
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
    print("Context7 (Antigravity): hosted HTTP ping PASS; authentication and MCP tool calls NOT VERIFIED (check agy /mcp)")
    return 0


def main(argv=None, *, directory=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    st = sub.add_parser("status")
    st.add_argument("--menu", action="store_true")
    sub.add_parser("menu-state", help="Passive state for Remote Dev menus")
    sub.add_parser("plan")
    sub.add_parser("remove").add_argument("--yes", action="store_true")
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
    if args.command == "menu-state":
        return menu_state(target)
    if args.command == "plan":
        return plan(target)
    # Healthy reinstall and already-absent removal are no-ops without a prompt.
    # Never inspect the vendor's OAuth token store.
    try:
        current, _ = using_config(target, lambda _ops, _fd, data, _info: inspect(data))
    except MaintenanceError:
        current = "blocked"
    if args.command == "reinstall" and current == "managed":
        return reinstall(target)
    if args.command == "remove" and current == "absent":
        return remove(target)
    if current in {"blocked", "custom", "custom-auth"} or (
            args.command == "remove" and current != "managed"):
        print("Context7 (Antigravity): action BLOCKED; manual review required")
        return 3
    if not args.yes:
        if not sys.stdin.isatty():
            print("Context7 (Antigravity): explicit confirmation required (--yes)", file=sys.stderr)
            return 2
        action = ("REMOVE" if args.command == "remove"
                  else "INSTALL" if args.command == "reinstall" and current == "absent"
                  else "REINSTALL" if args.command == "reinstall" else "TEST")
        answer = input(f"Type {action} to confirm {args.command}: ")
        if answer != action:
            print("Context7 (Antigravity): cancelled", file=sys.stderr)
            return 2
    if args.command == "remove":
        return remove(target)
    return reinstall(target) if args.command == "reinstall" else test(target)


if __name__ == "__main__":
    raise SystemExit(main())
