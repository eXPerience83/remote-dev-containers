"""Discovery of direct Docker build downloads."""
from __future__ import annotations

import re
from pathlib import Path

from .apt_scan import apt_packages_from_command
from .docker_parse import COMMAND_PREFIX, docker_instructions, executable_name, run_commands
from .io import InventoryError

URL_RE = re.compile(r"https://[^\s\"'<>]+")
NETWORK_RE = re.compile(COMMAND_PREFIX + r"(?:curl|wget)(?=\s|$)")
GIT_RE = re.compile(COMMAND_PREFIX + r"git(?=\s|$)")
GIT_VALUE_OPTIONS = {
    "-c",
    "-C",
    "--exec-path",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
}


def _git_subcommand(tokens: list[str], path: Path) -> str | None:
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return tokens[index + 1] if index + 1 < len(tokens) else None
        if token in GIT_VALUE_OPTIONS:
            if index + 1 >= len(tokens):
                raise InventoryError(f"Git option {token} has no value in {path}")
            index += 2
            continue
        if token.startswith(tuple(f"{option}=" for option in GIT_VALUE_OPTIONS if option.startswith("--"))):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token
    return None


def _network_command(tokens: list[str], path: Path) -> bool:
    if not tokens:
        return False
    executable = executable_name(tokens[0])
    if executable in {"curl", "wget"}:
        return True
    return executable == "git" and _git_subcommand(tokens, path) == "clone"


def _contains_hidden_fetch(tokens: list[str], path: Path) -> bool:
    text = " ".join(tokens)
    if NETWORK_RE.search(text):
        return True
    for index, token in enumerate(tokens):
        if executable_name(token) != "git":
            continue
        try:
            if _git_subcommand(tokens[index:], path) == "clone":
                return True
        except InventoryError:
            return True
    return bool(GIT_RE.search(text) and re.search(r"(?:^|\s)clone(?=\s|$)", text))


def docker_download_urls(path: Path) -> list[str]:
    """Return literal HTTPS sources or reject unparsed fetch forms."""
    urls: set[str] = set()
    for instruction in docker_instructions(path):
        if instruction.startswith("ADD "):
            urls.update(match.group(0).rstrip("),.;") for match in URL_RE.finditer(instruction))
        for tokens in run_commands(instruction, path):
            if apt_packages_from_command(tokens, path) is not None:
                continue
            text = " ".join(tokens)
            direct = _network_command(tokens, path)
            if _contains_hidden_fetch(tokens, path) and not direct:
                raise InventoryError(f"unsupported compound shell around a network fetch in {path}: {text}")
            if not direct:
                continue
            found = [match.group(0).rstrip("),.;") for match in URL_RE.finditer(text)]
            if not found:
                raise InventoryError(f"network fetch must contain a literal HTTPS source in {path}: {text}")
            urls.update(found)
    return sorted(urls)


def instruction_runs_network_fetch(instruction: str) -> bool:
    path = Path("Dockerfile")
    return any(_network_command(tokens, path) for tokens in run_commands(instruction, path))
