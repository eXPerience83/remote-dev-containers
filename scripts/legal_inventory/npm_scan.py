"""Discovery of globally installed npm packages."""
from __future__ import annotations

import re
from pathlib import Path

from .docker_parse import docker_instructions, executable_name, run_commands, strip_command_prefix
from .io import InventoryError

PACKAGE_SPEC_RE = re.compile(
    r"(?P<name>@?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)@\$\{(?P<key>[A-Z][A-Z0-9_]*)\}"
)

# Keep this command namespace aligned with npm CLI 11.12.1's
# lib/utils/cmd-list.js. npm resolves camelCase, exact commands/aliases and then
# unambiguous prefixes across this complete namespace.
NPM_COMMANDS = {
    "access", "adduser", "audit", "bugs", "cache", "ci", "completion", "config",
    "dedupe", "deprecate", "diff", "dist-tag", "docs", "doctor", "edit", "exec",
    "explain", "explore", "find-dupes", "fund", "get", "help", "help-search", "init",
    "install", "install-ci-test", "install-test", "link", "ll", "login", "logout", "ls",
    "org", "outdated", "owner", "pack", "ping", "pkg", "prefix", "profile", "prune",
    "publish", "query", "rebuild", "repo", "restart", "root", "run", "sbom", "search",
    "set", "shrinkwrap", "star", "stars", "start", "stop", "team", "test", "token",
    "trust", "undeprecate", "uninstall", "unpublish", "unstar", "update", "version",
    "view", "whoami",
}
NPM_ALIASES = {
    "author": "owner", "home": "docs", "issues": "bugs", "info": "view", "show": "view",
    "find": "search", "add": "install", "unlink": "uninstall", "remove": "uninstall",
    "rm": "uninstall", "r": "uninstall", "un": "uninstall", "rb": "rebuild",
    "list": "ls", "ln": "link", "create": "init", "i": "install", "it": "install-test",
    "cit": "install-ci-test", "up": "update", "c": "config", "s": "search", "se": "search",
    "tst": "test", "t": "test", "ddp": "dedupe", "v": "view", "run-script": "run",
    "clean-install": "ci", "clean-install-test": "install-ci-test", "x": "exec",
    "why": "explain", "la": "ll", "verison": "version", "ic": "ci", "innit": "init",
    "in": "install", "ins": "install", "inst": "install", "insta": "install",
    "instal": "install", "isnt": "install", "isnta": "install", "isntal": "install",
    "isntall": "install", "install-clean": "ci", "isntall-clean": "ci", "hlep": "help",
    "dist-tags": "dist-tag", "upgrade": "update", "udpate": "update", "rum": "run",
    "sit": "install-ci-test", "urn": "run", "ogr": "org", "add-user": "adduser",
}
NPM_INSTALL_COMMANDS = {"install", "ci", "install-test", "install-ci-test"}
NPM_TERMINAL_OPTIONS = {"--help", "-h", "--version", "-v", "--versions"}
NPM_BOOLEAN_OPTIONS = {
    "--audit", "--dry-run", "--force", "--foreground-scripts", "--fund",
    "--ignore-scripts", "--json", "--silent", "--verbose", "--yes", "-y",
}
BOOLEAN_VALUES = {"true": True, "false": False}
# Only options that unambiguously consume the following token belong here.
# Unknown pre-command options are rejected instead of guessing and potentially
# treating their value as the npm command.
NPM_VALUE_OPTIONS = {
    "--auth-type", "--cache", "--https-proxy", "--install-strategy", "--location",
    "--loglevel", "--logs-dir", "--node-options", "--omit", "--otp", "--prefix",
    "--proxy", "--registry", "--save-prefix", "--scope", "--script-shell", "--tag",
    "--user-agent", "--userconfig", "--workspace", "-w",
}


def _normalize_npm_command(command: str) -> str:
    """Apply npm's camelCase-to-kebab-case command normalization."""
    return re.sub(r"([A-Z])", lambda match: "-" + match.group(1).lower(), command)


def _resolve_alias(command: str) -> str:
    """Resolve npm alias chains to their canonical command."""
    seen: set[str] = set()
    while command in NPM_ALIASES:
        if command in seen:
            raise InventoryError(f"npm command alias cycle detected at {command}")
        seen.add(command)
        command = NPM_ALIASES[command]
    return command


def _resolve_npm_command(command: str) -> str | None:
    """Mirror npm's exact/alias/unambiguous-prefix command dereferencing."""
    normalized = _normalize_npm_command(command)
    if normalized in NPM_COMMANDS:
        return normalized
    if normalized in NPM_ALIASES:
        return _resolve_alias(normalized)
    candidates = sorted(name for name in NPM_COMMANDS | set(NPM_ALIASES) if name.startswith(normalized))
    if len(candidates) != 1:
        return None
    return _resolve_alias(candidates[0])


def _following_boolean(tokens: list[str], index: int) -> tuple[int, bool | None]:
    """Consume a separate explicit true/false value when npm accepts one."""
    if index + 1 >= len(tokens):
        return index + 1, None
    value = BOOLEAN_VALUES.get(tokens[index + 1].lower())
    if value is None:
        return index + 1, None
    return index + 2, value


def _attached_boolean(token: str, option: str, path: Path) -> bool | None:
    prefix = option + "="
    if not token.startswith(prefix):
        return None
    raw_value = token[len(prefix):].lower()
    if raw_value not in BOOLEAN_VALUES:
        raise InventoryError(f"npm option {option} has invalid Boolean value {raw_value!r} in {path}")
    return BOOLEAN_VALUES[raw_value]


def _consume_option(tokens: list[str], index: int, path: Path) -> tuple[int, bool | None, bool]:
    """Consume one npm option and return an optional global-mode override."""
    token = tokens[index]
    if token in NPM_TERMINAL_OPTIONS:
        return index + 1, None, True

    if token in {"-g", "--global"}:
        next_index, explicit = _following_boolean(tokens, index)
        return next_index, True if explicit is None else explicit, False
    attached_global = _attached_boolean(token, "--global", path)
    if attached_global is not None:
        return index + 1, attached_global, False

    if token == "--location":
        if index + 1 >= len(tokens):
            raise InventoryError(f"npm option {token} has no value in {path}")
        return index + 2, tokens[index + 1] == "global", False
    if token.startswith("--location="):
        return index + 1, token.split("=", 1)[1] == "global", False

    if token in NPM_VALUE_OPTIONS:
        if index + 1 >= len(tokens):
            raise InventoryError(f"npm option {token} has no value in {path}")
        return index + 2, None, False

    if token in NPM_BOOLEAN_OPTIONS or token.startswith("--no-"):
        next_index, _ = _following_boolean(tokens, index)
        return next_index, None, False
    if any(token.startswith(option + "=") for option in NPM_BOOLEAN_OPTIONS):
        option = token.split("=", 1)[0]
        _attached_boolean(token, option, path)
        return index + 1, None, False

    if token.startswith("--") and "=" in token:
        return index + 1, None, False
    if token.startswith("-"):
        raise InventoryError(
            f"unsupported npm option before command in {path}: {token}; "
            "classify whether it consumes a value before relying on legal discovery"
        )
    return index, None, False


def _npm_layout(tokens: list[str], path: Path) -> tuple[int, bool] | None:
    """Return the npm install subcommand index and whether it is global."""
    tokens = strip_command_prefix(tokens)
    if not tokens:
        return None
    text = " ".join(tokens)
    if executable_name(tokens[0]) != "npm":
        for index, token in enumerate(tokens):
            if executable_name(token) != "npm":
                continue
            nested = _npm_layout(tokens[index:], path)
            if nested is not None:
                raise InventoryError(f"unsupported compound shell around an npm install in {path}: {text}")
        return None

    subcommand_index: int | None = None
    global_mode = False
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            if index < len(tokens):
                subcommand_index = index
            break
        if not token.startswith("-"):
            subcommand_index = index
            break
        index, global_override, terminal_query = _consume_option(tokens, index, path)
        if global_override is not None:
            global_mode = global_override
        if terminal_query:
            return None

    if subcommand_index is None:
        return None
    resolved_command = _resolve_npm_command(tokens[subcommand_index])
    if resolved_command not in NPM_INSTALL_COMMANDS:
        return None

    index = subcommand_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            break
        if not token.startswith("-"):
            index += 1
            continue
        index, global_override, terminal_query = _consume_option(tokens, index, path)
        if global_override is not None:
            global_mode = global_override
        if terminal_query:
            return None
    return subcommand_index, global_mode


def global_npm_specs(dockerfile: Path) -> list[tuple[str, str]]:
    """Discover every globally installed npm package/version-key pair."""
    result: set[tuple[str, str]] = set()
    for instruction in docker_instructions(dockerfile):
        for raw_tokens in run_commands(instruction, dockerfile):
            tokens = strip_command_prefix(raw_tokens)
            layout = _npm_layout(tokens, dockerfile)
            if layout is None:
                continue
            subcommand_index, global_mode = layout
            if not global_mode:
                raise InventoryError(
                    f"local npm installs are unsupported by legal discovery in {dockerfile}: {' '.join(tokens)}; "
                    "use an explicitly inventoried global package or preserve the complete local dependency notices"
                )

            package_tokens: list[str] = []
            index = subcommand_index + 1
            while index < len(tokens):
                token = tokens[index]
                if token == "--":
                    package_tokens.extend(tokens[index + 1:])
                    break
                if token.startswith("-"):
                    index, _, terminal_query = _consume_option(tokens, index, dockerfile)
                    if terminal_query:
                        package_tokens = []
                        break
                    continue
                package_tokens.append(token)
                index += 1

            if not package_tokens:
                raise InventoryError(f"global npm install has no package spec in {dockerfile}: {' '.join(tokens)}")
            for token in package_tokens:
                match = PACKAGE_SPEC_RE.fullmatch(token)
                if not match:
                    raise InventoryError(
                        f"unsupported global npm package spec {token!r} in {dockerfile}; "
                        "pin it through versions.env as package@${VERSION_KEY}"
                    )
                result.add((match.group("name"), match.group("key")))
    return sorted(result)
