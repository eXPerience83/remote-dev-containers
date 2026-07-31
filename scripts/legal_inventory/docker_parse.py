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


def instruction_payload(instruction: str, keyword: str) -> str | None:
    """Return an instruction payload using Docker's case-insensitive keywords."""
    match = re.match(r"^([A-Za-z]+)(?:\s+|$)(.*)$", instruction, flags=re.DOTALL)
    if match is None or match.group(1).upper() != keyword.upper():
        return None
    return match.group(2).strip()


def docker_instructions(path: Path) -> list[str]:
    """Join continuation lines and reject RUN heredocs we cannot inspect."""
    instructions: list[str] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        run_payload = instruction_payload(line, "RUN") if not current else None
        if run_payload is not None and HEREDOC_RE.search(run_payload):
            raise InventoryError(f"RUN heredocs are unsupported by legal discovery in {path}")
        current.append(line.rstrip("\\").strip())
        if line.endswith("\\"):
            continue
        instruction = " ".join(filter(None, current))
        if instruction_payload(instruction, "ONBUILD") is not None:
            raise InventoryError(
                f"ONBUILD is unsupported by legal discovery in {path}; "
                "deferred triggers can introduce content after inventory validation"
            )
        run_payload = instruction_payload(instruction, "RUN")
        if run_payload is not None and HEREDOC_RE.search(run_payload):
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


def _reject_legacy_substitutions(command: str) -> None:
    """Reject backtick substitution, whose escaping rules are intentionally not emulated."""
    index = 0
    quote: str | None = None
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            index += 1
            continue
        if character == "`" and quote != "'":
            raise InventoryError(
                "legacy backtick command substitutions are unsupported by legal discovery; use $(...)"
            )
        index += 1


def _command_substitutions(command: str) -> list[str]:
    """Extract balanced shell command substitutions, including nested ones."""
    _reject_legacy_substitutions(command)
    substitutions: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
            index += 1
            continue
        if quote == "'" or not command.startswith("$(", index) or command.startswith("$((", index):
            index += 1
            continue

        start = index + 2
        cursor = start
        depth = 1
        nested_quote: str | None = None
        while cursor < len(command):
            nested_character = command[cursor]
            if nested_character == "\\" and nested_quote != "'":
                cursor += 2
                continue
            if nested_character in {"'", '"'}:
                if nested_quote is None:
                    nested_quote = nested_character
                elif nested_quote == nested_character:
                    nested_quote = None
                cursor += 1
                continue
            if nested_quote is None:
                if command.startswith("$(", cursor):
                    depth += 1
                    cursor += 2
                    continue
                if nested_character == "(":
                    depth += 1
                elif nested_character == ")":
                    depth -= 1
                    if depth == 0:
                        substitutions.append(command[start:cursor])
                        index = cursor + 1
                        break
            cursor += 1
        else:
            raise InventoryError(f"unbalanced command substitution in shell instruction: {command}")
    return substitutions


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
    for substitution in _command_substitutions(command):
        result.extend(_expanded_commands(substitution))
    for raw in _shell_commands(command):
        result.extend(_expanded_tokens(raw, command))
    return result


def run_commands(instruction: str, path: Path) -> list[list[str]]:
    """Return argv lists from shell-form or JSON exec-form RUN."""
    payload = instruction_payload(instruction, "RUN")
    if payload is None:
        return []
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
    result: list[list[str]] = []
    for substitution in _command_substitutions(" ".join(value)):
        result.extend(_expanded_commands(substitution))
    result.extend(_expanded_tokens(value, payload))
    return result
