"""Discovery of direct Docker build downloads."""
from __future__ import annotations

import re
from pathlib import Path

from .apt_scan import apt_packages_from_command
from .docker_parse import COMMAND_PREFIX, docker_instructions, executable_name, run_commands
from .io import InventoryError

URL_RE = re.compile(r"https://[^\s\"'<>]+")
NETWORK_RE = re.compile(COMMAND_PREFIX + r"(?:curl|wget)(?=\s|$)")
GIT_CLONE_RE = re.compile(COMMAND_PREFIX + r"git\s+clone(?=\s|$)")


def _network_command(tokens: list[str]) -> bool:
    return bool(tokens) and (
        executable_name(tokens[0]) in {"curl", "wget"}
        or (
            executable_name(tokens[0]) == "git"
            and len(tokens) > 1
            and executable_name(tokens[1]) == "clone"
        )
    )


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
            direct = _network_command(tokens)
            if (NETWORK_RE.search(text) or GIT_CLONE_RE.search(text)) and not direct:
                raise InventoryError(f"unsupported compound shell around a network fetch in {path}: {text}")
            if not direct:
                continue
            found = [match.group(0).rstrip("),.;") for match in URL_RE.finditer(text)]
            if not found:
                raise InventoryError(f"network fetch must contain a literal HTTPS source in {path}: {text}")
            urls.update(found)
    return sorted(urls)


def instruction_runs_network_fetch(instruction: str) -> bool:
    """Return whether one instruction directly invokes a downloader."""
    return any(_network_command(tokens) for tokens in run_commands(instruction, Path("Dockerfile")))
