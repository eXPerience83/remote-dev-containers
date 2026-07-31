"""Discovery of package-manager installer commands requiring inventory ownership."""
from __future__ import annotations

import re
from pathlib import Path

from .docker_parse import COMMAND_PREFIX, docker_instructions, executable_name, run_commands, strip_command_prefix
from .io import InventoryError

INSTALLER_RE = re.compile(
    COMMAND_PREFIX + r"(?:apk|bun|cargo|composer|dnf|dotnet|gem|go|pip3?|pipx|pnpm|poetry|python3?|uv|yarn|yum)(?=\s|$)"
)
PIP_VALUE_OPTIONS = {
    "--cache-dir",
    "--cert",
    "--client-cert",
    "--config-settings",
    "--debug",
    "--index-url",
    "--log",
    "--proxy",
    "--python",
    "--retries",
    "--root-user-action",
    "--timeout",
    "--trusted-host",
    "--use-feature",
    "--use-deprecated",
    "--extra-index-url",
    "--find-links",
    "-f",
    "-i",
}


def _skip_options(tokens: list[str], index: int, value_options: set[str], path: Path, label: str) -> int:
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in value_options:
            if index + 1 >= len(tokens):
                raise InventoryError(f"{label} option {token} has no value in {path}")
            index += 2
        elif token.startswith("-"):
            index += 1
        else:
            break
    return index


def _is_installer(tokens: list[str], path: Path) -> bool:
    tokens = strip_command_prefix(tokens)
    if not tokens:
        return False
    executable = executable_name(tokens[0])
    text = " ".join(tokens)
    if any(token in {"--help", "-h", "--version", "-v", "help", "version"} for token in tokens[1:]):
        return False

    if executable in {"pip", "pip3"}:
        index = _skip_options(tokens, 1, PIP_VALUE_OPTIONS, path, "pip")
        if index < len(tokens) and tokens[index] in {"install", "download"}:
            return True
        raise InventoryError(f"unsupported pip subcommand for legal discovery in {path}: {text}")

    if executable in {"python", "python3"}:
        try:
            module_index = tokens.index("-m", 1)
        except ValueError:
            return False
        if module_index + 1 >= len(tokens) or tokens[module_index + 1] != "pip":
            return False
        index = _skip_options(tokens, module_index + 2, PIP_VALUE_OPTIONS, path, "pip")
        if index < len(tokens) and tokens[index] in {"install", "download"}:
            return True
        raise InventoryError(f"unsupported python -m pip subcommand for legal discovery in {path}: {text}")

    if executable == "uv":
        index = _skip_options(tokens, 1, set(), path, "uv")
        if index < len(tokens) and tokens[index] in {"add", "sync"}:
            return True
        if index >= len(tokens) or tokens[index] not in {"pip", "tool"}:
            raise InventoryError(f"unsupported uv subcommand for legal discovery in {path}: {text}")
        index = _skip_options(tokens, index + 1, set(), path, "uv")
        if index < len(tokens) and tokens[index] == "install":
            return True
        raise InventoryError(f"unsupported uv subcommand for legal discovery in {path}: {text}")

    if executable in {"cargo", "gem"}:
        index = _skip_options(tokens, 1, set(), path, executable)
        allowed = {"install"} if executable == "cargo" else {"install", "fetch"}
        if index < len(tokens) and tokens[index] in allowed:
            return True
        raise InventoryError(f"unsupported {executable} subcommand for legal discovery in {path}: {text}")

    if executable == "go":
        index = _skip_options(tokens, 1, set(), path, "go")
        if index < len(tokens) and (tokens[index] in {"get", "install"} or tokens[index:index + 2] == ["mod", "download"]):
            return True
        raise InventoryError(f"unsupported go subcommand for legal discovery in {path}: {text}")

    if executable in {"pipx", "poetry", "pnpm", "yarn", "bun", "apk", "dnf", "yum"}:
        index = _skip_options(tokens, 1, set(), path, executable)
        commands = {
            "pipx": {"install"},
            "poetry": {"add", "install", "sync", "lock", "update"},
            "pnpm": {"add", "i", "install"},
            "yarn": {"add", "install"},
            "bun": {"add", "i", "install"},
            "apk": {"add", "fetch"},
            "dnf": {"groupinstall", "install", "localinstall", "reinstall"},
            "yum": {"groupinstall", "install", "localinstall", "reinstall"},
        }
        if index >= len(tokens) and executable in {"yarn", "pnpm", "bun"}:
            return True
        if index < len(tokens) and tokens[index] in commands[executable]:
            return True
        raise InventoryError(f"unsupported {executable} subcommand for legal discovery in {path}: {text}")

    if executable == "dotnet":
        index = _skip_options(tokens, 1, set(), path, "dotnet")
        return index + 1 < len(tokens) and tokens[index : index + 2] == ["tool", "install"]

    if executable == "composer":
        index = _skip_options(tokens, 1, set(), path, "composer")
        return index + 1 < len(tokens) and tokens[index : index + 2] == ["global", "require"]

    if INSTALLER_RE.search(text):
        raise InventoryError(f"unsupported compound shell around an installer command in {path}: {text}")
    return False


def discovered_installer_instructions(dockerfile: Path) -> list[str]:
    """Find installer RUN instructions that need an explicit inventory marker."""
    result: set[str] = set()
    for instruction in docker_instructions(dockerfile):
        commands = run_commands(instruction, dockerfile)
        if any(_is_installer(tokens, dockerfile) for tokens in commands):
            result.add(instruction)
    return sorted(result)
