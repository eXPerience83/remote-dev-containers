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


def role_arm(name: str, role: str, number: int) -> str:
    """Get exactly the role-qualified action arm, excluding other providers."""
    body = function(name)
    match = re.search(
        rf"^    {re.escape(role)}:{number}\)\n(.*?)"
        r"(?=^    (?:(?:codex|antigravity):[0-9]+|\*)\))",
        body,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        raise AssertionError(f"{name}: missing {role}:{number} action")
    return match.group(1)


def assert_role_dispatch() -> None:
    # Similar labels must not be allowed to execute another provider's CLI.
    main = {
        ("codex", 1): ('run_codex_action "Codex"',),
        ("codex", 2): ('run_codex_action "Codex resume" resume',),
        ("codex", 4): ("choose_next_codex_mode",),
        ("codex", 5): ("show_agent_manage_menu",),
        ("antigravity", 1): ('run_antigravity_action "Antigravity"',),
        ("antigravity", 2): ('run_antigravity_action "Antigravity continue" --continue',),
        ("antigravity", 4): ("show_antigravity_approval_menu",),
        ("antigravity", 5): ("show_agent_manage_menu",),
    }
    manage = {
        ("codex", 1): ("remote-dev-codex-runtime update",),
        ("codex", 2): ("remote-dev-codex-runtime remove",),
        ("codex", 3): ("run_credential_command codex login --device-auth",),
        ("antigravity", 1): ("manage_state", "== absent", "remote-dev-install-antigravity"),
        ("antigravity", 2): ("manage_state", "== installed", "== damaged", "remote-dev-update-antigravity"),
        ("antigravity", 3): ("sign-in is handled by Google",),
    }
    for func_name, cases in (
        ("dispatch_agent_main_choice", main),
        ("dispatch_agent_manage_choice", manage),
    ):
        body = function(func_name)
        if 'case "$role:$1" in' not in body or "*)\n" not in body:
            raise AssertionError(f"{func_name}: missing role qualification / default deny")
        for (role, number), phrases in cases.items():
            arm = role_arm(func_name, role, number)
            for phrase in phrases:
                if phrase not in arm:
                    raise AssertionError(f"{func_name} {role}:{number}: missing {phrase}")
            if role == "codex" and any(
                phrase in arm for phrase in ("run_antigravity_action", "remote-dev-install-antigravity", "remote-dev-update-antigravity")
            ):
                raise AssertionError("Codex action accidentally invokes Antigravity")
            if role == "antigravity" and any(
                phrase in arm for phrase in ("run_codex_action", "remote-dev-codex-runtime", "codex login")
            ):
                raise AssertionError("Antigravity action accidentally invokes Codex")
        expected = {(role, number) for role, number in cases}
        actual = set(
            (role, int(number))
            for role, number in re.findall(
                r"^    (codex|antigravity):([0-9]+)\)", body, flags=re.MULTILINE
            )
        )
        if actual != expected:
            raise AssertionError(f"{func_name}: unexpected action arms: {actual ^ expected}")


def assert_agent_menu_contract() -> None:
    shared = options(function("print_shared_agent_menu_tail"))
    expected_shared = {
        6: "MCP integrations...",
        7: "Sign in to GitHub CLI",
        8: "Run diagnostics",
        9: "Open container shell",
        0: "Exit this tmux session",
    }
    if shared != expected_shared:
        raise AssertionError(f"shared main-menu tail drifted: {shared}")

    rendered_main = options(function("print_agent_main_menu"))
    expected_main = {
        1: "Start ${role_name}",
        2: "${main_resume_label}",
        3: "Projects...",
        4: "Approval settings...",
        5: "Manage ${role_name}...",
    }
    if rendered_main != expected_main:
        raise AssertionError(f"shared agent main-menu text drifted: {rendered_main}")
    if sorted(rendered_main | shared) != list(range(10)):
        raise AssertionError("agent menu must provide exactly 0-9")

    rendered_manage = options(function("print_agent_manage_menu"))
    if rendered_manage != {
        1: "${manage_choice1}",
        2: "${manage_choice2}",
        3: "${manage_choice3}",
        0: "Back",
    }:
        raise AssertionError(f"shared agent Manage labels drifted: {rendered_manage}")
    for name in ("agent_menu_role_name", "configure_agent_main_menu", "configure_agent_manage_menu"):
        body = function(name)
        if "codex)" not in body or "antigravity)" not in body or "*)" not in body:
            raise AssertionError(f"{name}: both roles and fail-closed default are required")
    if "Resume session (current project)" not in function("configure_agent_main_menu"):
        raise AssertionError("Codex resume label drifted")
    if "Continue latest session (current project)" not in function("configure_agent_main_menu"):
        raise AssertionError("Antigravity continue label drifted")
    render_loop = function("show_agent_menu")
    for marker in (
        'configure_agent_main_menu "$role_name"',
        'print_agent_main_menu "$role_name"',
        'if is_shared_agent_menu_choice "$choice"; then',
        'handle_shared_agent_menu_choice "$choice"',
        'dispatch_agent_main_choice "$choice"',
    ):
        if marker not in render_loop:
            raise AssertionError(f"shared agent main-menu loop missing {marker}")
    manage_loop = function("show_agent_manage_menu")
    for marker in (
        "configure_agent_manage_menu",
        'print_agent_manage_menu "$role_name"',
        'dispatch_agent_manage_choice "$choice"',
    ):
        if marker not in manage_loop:
            raise AssertionError(f"shared agent management loop missing {marker}")

    shared_dispatch = function("handle_shared_agent_menu_choice")
    for marker in (
        "3) show_projects_menu", "6) show_mcp_integrations_menu",
        "7) if run_github_login", "8) run_diagnostics",
        '9) if run_interactive_and_harden "Container shell" bash --login',
        "0) exit 0",
    ):
        if marker not in shared_dispatch:
            raise AssertionError(f"shared dispatch contract missing {marker}")
    if "3|6|7|8|9|0) return 0" not in function("is_shared_agent_menu_choice"):
        raise AssertionError("shared recognition and dispatch disagree")

    if (
        "show_agent_menu" in function("show_shell_menu")
        or "Open container shell" not in function("show_shell_menu")
        or "bash --login" not in function("show_shell_menu")
    ):
        raise AssertionError("independent shell recovery role changed")
    projects = function("show_projects_menu")
    if "0) Back" not in projects or "0|4)" not in projects:
        raise AssertionError("Projects must show 0 Back and retain old 4 alias")
    approval = function("print_common_approval_mode_choices")
    for item in ("Use configured mode for next launch", "Autonomous for next launch", "Guarded for next launch"):
        if item not in approval:
            raise AssertionError(f"approval common wording changed: {item}")
    for name in ("choose_next_codex_mode", "show_antigravity_approval_menu"):
        if "print_common_approval_mode_choices" not in function(name):
            raise AssertionError(f"{name}: no shared approval labels")
    assert_role_dispatch()


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
    integrations = function("show_mcp_integrations_menu")
    for token in ('case "$role" in', 'codex) show_context7_menu', 'antigravity) show_antigravity_context7_menu', '*)'):
        if token not in integrations:
            raise AssertionError(f"fail-closed provider-specific Context7 navigation missing: {token}")


def assert_full_nested_menu_contract() -> None:
    """Audit *every* visible nested menu, prompt and provider path, not just the titles."""
    projects = function("show_projects_menu")
    if options(projects) != {
        1: "Select project", 2: "Create project", 3: "Delete project", 0: "Back"
    }:
        raise AssertionError("Projects menu options or Back drifted")
    picker = function("choose_project_name")
    if ("printf '0) Back" not in picker
            or "index == ${#projects[@]}" not in picker):
        raise AssertionError("dynamic project picker must show 0 Back and preserve legacy N+1")
    if "Type the exact project name to confirm:" not in function("delete_project_action"):
        raise AssertionError("project deletion lost its exact-name confirmation")
    if "remote_dev_delete_project" not in function("delete_project_action"):
        raise AssertionError("project deletion lost its ownership/boundary validation")
    if "0|4)" not in projects:
        raise AssertionError("Projects lost historic 4 Back alias")

    # Start/continue actions already have role-qualified explicit dispatch.
    # Project selectors and nested approvals must not accidentally change mode
    # for more than one launch.
    for provider, approval_name in (
        ("codex", "choose_next_codex_mode"),
        ("antigravity", "show_antigravity_approval_menu"),
    ):
        approval = function(approval_name)
        if 'print_common_approval_mode_choices' not in approval or "0) Back" not in approval:
            raise AssertionError(f"{provider}: missing common approval choices or Back")
        if "next_" + provider + "_mode=" not in approval:
            raise AssertionError(f"{provider}: approval choice not scoped to provider")
    guarded = function("set_antigravity_guarded_preset")
    if ('menu_confirm_yes_no "Apply Guarded preset $preset?"' not in guarded
            or "remote-dev-antigravity-policy set-preset" not in guarded):
        raise AssertionError("persistent Guarded preset must be explicitly confirmed")
    if "remote-dev-antigravity-policy" in function("choose_next_codex_mode"):
        raise AssertionError("Codex approval must never invoke AGY settings writer")
    for provider, runner in (
        ("codex", "run_codex_action"),
        ("antigravity", "run_antigravity_action"),
    ):
        body = function(runner)
        if 'next_' + provider + '_mode=""' not in body:
            raise AssertionError(f"{provider}: one-launch override was not consumed")

    shell = function("show_shell_menu")
    if options(shell) != {
        1: "Open container shell", 2: "Sign in to GitHub CLI",
        3: "Run diagnostics", 0: "Exit this tmux session",
    } or "0|4)" not in shell:
        raise AssertionError("emergency Shell navigation must show 0 Exit with historic alias")
    if "bash --login" not in shell or "run_github_login" not in shell:
        raise AssertionError("emergency Shell actions changed")
    integrations = function("show_mcp_integrations_menu")
    if options(integrations) != {1: "Context7...", 0: "Back"}:
        raise AssertionError("MCP integrations menu changed unexpectedly")

    # A nonmutating remote *test* is y/N in both menus, even though the
    # underlying direct CLI contract still has provider-specific confirmations.
    test = function("run_confirmed_context7_test")
    for token in (
        "menu_confirm_yes_no", "test --yes", "no network request was made",
        'run_context7_action "$label" "$manager"',
    ):
        if token not in test:
            raise AssertionError(f"shared Context7 test lost {token}")
    change = function("run_confirmed_context7_change")
    for token in (
        "menu_confirm_word", "codex:REMOVE", "antigravity:REMOVE",
        "codex:REINSTALL|antigravity:REINSTALL", '"$@" --yes',
    ):
        if token not in change:
            raise AssertionError(f"Context7 scoped change confirmation lost {token}")
    for name, provider, manager in (
        ("show_context7_menu", "Codex", "remote-dev-context7"),
        ("show_antigravity_context7_menu", "Antigravity", "remote-dev-context7-antigravity"),
    ):
        role = function(name)
        for token in (
            "run_confirmed_context7_test", "run_confirmed_context7_change REMOVE",
            'print_context7_menu_options', "0)",
        ):
            if token not in role:
                raise AssertionError(f"{provider} Context7 submenu lost {token}")
        if manager not in role or "manager" not in role:
            raise AssertionError(f"{provider} must dispatch its own Context7 manager")
        if '"$manager" test;' in role:
            raise AssertionError(f"{provider} bypassed the shared consent prompt")
    if "reinstall --menu-safe" not in function("show_context7_menu"):
        raise AssertionError("Codex manager repair changed")
    if 'run_confirmed_context7_change REINSTALL' not in function("show_antigravity_context7_menu"):
        raise AssertionError("Antigravity repair bypasses scoped confirmation")

    # Context7 has two *further* Codex-owned interactive menus after the
    # parent Context7 submenu. They must also show 0 Cancel and retain their
    # own former numeric aliases without ever triggering installation.
    wrapper = (SOURCE.parent / "remote-dev-context7-entrypoint.sh").read_text(encoding="utf-8")
    chooser = (SOURCE.parent / "remote-dev-context7-device-login.py").read_text(encoding="utf-8")
    for marker in ('0) Cancel', '0|5)', 'exec "$device_login" --yes'):
        if marker not in wrapper:
            raise AssertionError(f"Context7 authentication wizard lost {marker}")
    for marker in ('print("0) Cancel")', 'choice in {"0", "3"}'):
        if marker not in chooser:
            raise AssertionError(f"Context7 CLI-version chooser lost {marker}")

    # Prevent EoF from implicitly executing other menu choices.
    for name in (
        "show_projects_menu", "show_antigravity_approval_menu",
        "show_context7_menu", "show_antigravity_context7_menu",
        "show_mcp_integrations_menu", "show_shell_menu",
        "show_agent_menu", "show_agent_manage_menu",
    ):
        if 'read -r -p "> " choice || return 0' not in function(name):
            raise AssertionError(f"{name} must exit on input EOF")
    for name in ("choose_project_name", "create_project_action", "delete_project_action"):
        if "|| return 1" not in function(name):
            raise AssertionError(f"{name} cannot treat missing input as consent")


def main() -> None:
    assert_agent_menu_contract()
    assert_context7_contract()
    assert_full_nested_menu_contract()
    print("Codex/Antigravity full menu tree, prompts and provider routing: OK")


if __name__ == "__main__":
    main()
