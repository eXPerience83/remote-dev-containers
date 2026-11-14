#!/usr/bin/env python3
"""Protect shared option numbering across Codex and Antigravity menus.

The existing Bash fixture tests exercise actions per role. This structural
contract protects shared options against future drift at their definition.
The shell-only emergency menu is intentionally independent.
"""

from __future__ import annotations

import re
from pathlib import Path


SOURCE = Path(__file__).with_name("remote-dev-menu.sh")
MENU = SOURCE.read_text(encoding="utf-8")


def function(name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n",
        MENU,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"missing or malformed menu helper: {name}")
    return match.group(1)


def options(body: str) -> dict[int, str]:
    choices = re.findall(r"^(\d+)\) (.+)$", body, flags=re.MULTILINE)
    nums = [int(number) for number, _ in choices]
    if len(set(nums)) != len(nums):
        raise AssertionError(f"duplicate visible menu option: {nums}")
    return {int(number): label for number, label in choices}


def assert_agent_menu_contract() -> None:
    shared = options(function("print_shared_agent_menu_tail"))
    expected_shared = {
        9: "Sign in to GitHub CLI",
        10: "Run diagnostics",
        11: "Open a login shell",
        12: "Exit this tmux session",
    }
    if shared != expected_shared:
        raise AssertionError(f"shared main-menu tail drifted: {shared}")

    guard = function("is_shared_agent_menu_choice")
    if "3|7|9|10|11|12) return 0" not in guard:
        raise AssertionError("shared option recognition disagrees with dispatcher")
    dispatch = function("handle_shared_agent_menu_choice")
    dispatcher_choices = [
        int(number)
        for number in re.findall(r"^    (\d+)\)", dispatch, flags=re.MULTILINE)
    ]
    if dispatcher_choices != [3, 7, 9, 10, 11, 12]:
        raise AssertionError(f"shared dispatch contract drifted: {dispatcher_choices}")
    for call in (
        "3) show_projects_menu",
        "7) show_mcp_integrations_menu",
        "9) if run_github_login",
        "10) run_diagnostics",
        '11) if run_interactive_and_harden "Login shell"',
        "12) exit 0",
    ):
        if call not in dispatch:
            raise AssertionError(f"missing common main-menu action: {call}")

    menus: dict[str, dict[int, str]] = {}
    for role in ("codex", "antigravity"):
        body = function(f"show_{role}_menu")
        if body.count("    print_shared_agent_menu_tail\n") != 1:
            raise AssertionError(f"{role}: shared footer is not printed exactly once")
        if body.count('if is_shared_agent_menu_choice "$choice"; then') != 1:
            raise AssertionError(f"{role}: common option guard must occur exactly once")
        if body.count('      handle_shared_agent_menu_choice "$choice"') != 1:
            raise AssertionError(f"{role}: shared actions must run outside a conditional")
        own = options(body)
        if sorted(own) != list(range(1, 9)):
            raise AssertionError(f"{role}: expected local options 1-8; got {sorted(own)}")
        if own[3] != "Projects..." or own[7] != "MCP integrations...":
            raise AssertionError(f"{role}: common option 3/7 title mismatch")
        menus[role] = own | shared
        if sorted(menus[role]) != list(range(1, 13)):
            raise AssertionError(f"{role}: missing or repeated main-menu slot")

    if menus["codex"][8] != "Sign in to Codex with device code":
        raise AssertionError("Codex device-code authentication label changed")
    if menus["antigravity"][8] != "Antigravity sign-in [handled during launch]":
        raise AssertionError("Antigravity native sign-in label changed")
    for number in (3, 7, 9, 10, 11, 12):
        if menus["codex"][number] != menus["antigravity"][number]:
            raise AssertionError(f"agent menus disagree on shared slot {number}")
    if "handle_shared_agent_menu_choice" in function("show_shell_menu"):
        raise AssertionError("shell recovery menu must remain independent")


def assert_context7_contract() -> None:
    helper = function("print_context7_menu_options")
    rendered = options(helper)
    if sorted(rendered) != [0, 1, 2, 3, 4, 5]:
        raise AssertionError(f"unexpected Context7 menu options: {sorted(rendered)}")
    if rendered[0] != "Back":
        raise AssertionError("Context7 back navigation changed")
    for number, label in {
        1: "Status and recovery diagnosis (offline)",
        2: "Test hosted connection (network; not a real MCP tool call)",
        4: "Install or repair Context7 registration",
    }.items():
        if rendered[number] != label:
            raise AssertionError(f"Context7 slot {number} drifted")
    for owned_label in (
        "Manage Context7 authentication (Codex private API key)",
        "Manage authentication using Antigravity /mcp",
        "Remove Remote Dev-managed Context7 registration and local key",
        "Remove Remote Dev-managed Context7 registration",
    ):
        if owned_label not in helper:
            raise AssertionError(f"missing role-specific Context7 choice: {owned_label}")

    for name in ("show_context7_menu", "show_antigravity_context7_menu"):
        body = function(name)
        if body.count("    print_context7_menu_options\n") != 1:
            raise AssertionError(f"{name}: not using shared Context7 options")
        handlers = [
            int(number)
            for number in re.findall(r"^      (\d+)\)", body, flags=re.MULTILINE)
        ]
        if handlers != [1, 2, 3, 4, 5, 0]:
            raise AssertionError(f"{name}: Context7 handler order drifted: {handlers}")

    if 'reinstall --menu-safe' not in function("show_context7_menu"):
        raise AssertionError("Codex must use locked, menu-safe selective repair")
    if 'reinstall --menu-safe' in function("show_antigravity_context7_menu"):
        raise AssertionError("Antigravity must keep its separate JSON manager")
    if 'show_context7_menu' not in function("show_mcp_integrations_menu"):
        raise AssertionError("Codex Context7 navigation missing")
    if 'show_antigravity_context7_menu' not in function("show_mcp_integrations_menu"):
        raise AssertionError("Antigravity Context7 navigation missing")


def main() -> None:
    assert_agent_menu_contract()
    assert_context7_contract()
    print("Codex/Antigravity main and Context7 menu parity: OK")


if __name__ == "__main__":
    main()
