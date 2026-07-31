"""Conservative parsing of Dockerfile RUN instructions."""
from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from .io import InventoryError

ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
CONTROL_RE = re.compile(r"^[;&|]+$")
HEREDOC_RE = re.compile(r"(?:^|\s)<<-?\s*['\"]?[A-Za-z_][A-Za-z0-9_]*")
COMMAND_PREFIX = r"(?:^|[\s!({=])(?:\$\()?(?:(?:/[A-Za-z0-9_.-]+)*/)?"
SHELLS = {"bash", "sh", "dash"}


def docker_instructions(path: Path) -> list[str]:
    """Join continuation lines and reject RUN heredocs we cannot inspect."""
    instructions: list[str] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not current and (not line or line.startswith("#")):
            continue
        if not current and line.startswith("RUN ") and HEREDOC_RE.search(line):
            raise InventoryError(f"RUN heredocs are unsupported by legal discovery in {path}")
        current.append(line.rstrip("\\").strip())
        if line.endswith("\\"):
            continue
        instruction = " ".join(filter(None, current))
        if instruction.startswith("RUN ") and HEREDOC_RE.search(instruction):
            raise InventoryError(f"RUN heredocs are unsupported by legal discovery in {path}")
        instructions.append(instruction)
        current = []
    if current:
        instructions.append(" ".join(filter(None, current)))
    return instructions


def executable_name(token: str) -> str:
    """Normalize punctuation around a potential executable token."""
    return Path(token.strip("!(){}[]$")).name


def strip_command_prefix(tokens: list[str]) -> list[str]:
    """Remove assignments and common command/env wrappers."""
    result = list(tokens)
    while result and (result[0].startswith("--mount=") or ASSIGNMENT_RE.fullmatch(result[0])):
        result.pop(0)
    while result:
        executable = executable_name(result[0])
        if executable in {"command", "exec"}:
            result.pop(0)
            while result and result[0].startswith("-"):
                result.pop(0)
            continue
        if executable != "env":
            break
        result.pop(0)
        while result:
            token = result[0]
            if ASSIGNMENT_RE.fullmatch(token) or token in {"-i", "--ignore-environment", "-0", "--null"}:
                result.pop(0)
            elif token in {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}:
                result.pop(0)
                if not result:
                    raise InventoryError(f"env option {token} has no value")
                result.pop(0)
            elif token.startswith(("--unset=", "--chdir=", "--split-string=")):
                result.pop(0)
            else:
                break
    return result


def _shell_commands(command: str) -> list[list[str]]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError as exc:
        raise InventoryError(f"cannot parse shell instruction: {command}") from exc
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if CONTROL_RE.fullmatch(token):
            if current:
                commands.append(current)
                current = []
        else:
            current.append(token)
    if current:
        commands.append(current)
    return commands


def _shell_command_option_index(tokens: list[str]) -> int | None:
    for index, token in enumerate(tokens[1:], 1):
        if token == "-c" or (
            token.startswith("-") and not token.startswith("--") and len(token) > 2 and token.endswith("c")
        ):
            return index
    return None


def _expanded_tokens(tokens: list[str], context: str) -> list[list[str]]:
    tokens = strip_command_prefix(tokens)
    if not tokens:
        return []
    if executable_name(tokens[0]) in SHELLS:
        option_index = _shell_command_option_index(tokens)
        if option_index is not None:
            if option_index + 1 >= len(tokens):
                raise InventoryError(f"shell -c command has no program text: {context}")
            return _expanded_commands(tokens[option_index + 1])
    return [tokens]


def _expanded_commands(command: str) -> list[list[str]]:
    result: list[list[str]] = []
    for raw in _shell_commands(command):
        result.extend(_expanded_tokens(raw, command))
    return result


def run_commands(instruction: str, path: Path) -> list[list[str]]:
    """Return argv lists from shell-form or JSON exec-form RUN."""
    if not instruction.startswith("RUN "):
        return []
    payload = instruction[4:].strip()
    while payload.startswith("--"):
        _, separator, payload = payload.partition(" ")
        if not separator:
            raise InventoryError(f"RUN option has no command in {path}")
        payload = payload.lstrip()
    if not payload.startswith("["):
        return _expanded_commands(payload)
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"invalid JSON-form RUN in {path}: {payload}") from exc
    if not isinstance(value, list) or not value or not all(isinstance(token, str) for token in value):
        raise InventoryError(f"JSON-form RUN must be a non-empty string array in {path}")
    return _expanded_tokens(value, payload)
