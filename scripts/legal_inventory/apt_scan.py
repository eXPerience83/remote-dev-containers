"""Discovery of direct APT package installations."""
from __future__ import annotations

import re
from pathlib import Path

from .docker_parse import COMMAND_PREFIX, docker_instructions, executable_name, run_commands, strip_command_prefix
from .io import InventoryError

APT_PACKAGE_RE = re.compile(r"[a-z0-9][a-z0-9+.-]*")
APT_INSTALL_RE = re.compile(COMMAND_PREFIX + r"apt(?:-get)?(?:\s+[^;&|]*)?\s+install(?=\s|$)")
APT_VALUE_OPTIONS = {"-c", "--config-file", "-o", "--option", "-t", "--target-release"}


def apt_packages_from_command(tokens: list[str], path: Path) -> list[str] | None:
    """Parse one direct apt/apt-get install command or return None."""
    tokens = strip_command_prefix(tokens)
    if not tokens:
        return None
    executable = executable_name(tokens[0])
    text = " ".join(tokens)
    if executable not in {"apt", "apt-get"}:
        if APT_INSTALL_RE.search(text):
            raise InventoryError(f"unsupported compound shell around an APT install in {path}: {text}")
        return None
    normalized = [executable_name(token) for token in tokens]
    try:
        install = normalized.index("install", 1)
    except ValueError:
        return None
    packages: list[str] = []
    index = install + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
        elif token in APT_VALUE_OPTIONS:
            if index + 1 >= len(tokens):
                raise InventoryError(f"APT option {token} has no value in {path}")
            index += 2
        elif token.startswith("-"):
            index += 1
        elif APT_PACKAGE_RE.fullmatch(token):
            packages.append(token)
            index += 1
        else:
            raise InventoryError(f"unsupported APT package token {token!r} in {path}")
    if not packages:
        raise InventoryError(f"APT install has no explicit package names in {path}: {text}")
    return packages


def parse_apt_packages(path: Path) -> list[str]:
    """Extract packages from every apt/apt-get install command."""
    packages: set[str] = set()
    count = 0
    for instruction in docker_instructions(path):
        for tokens in run_commands(instruction, path):
            found = apt_packages_from_command(tokens, path)
            if found is not None:
                count += 1
                packages.update(found)
    if not count:
        raise InventoryError(f"no APT packages discovered in {path}")
    return sorted(packages)
