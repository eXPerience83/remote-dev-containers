"""Discovery of direct Docker build downloads."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

from .apt_scan import apt_packages_from_command
from .docker_parse import COMMAND_PREFIX, docker_instructions, executable_name, instruction_payload, run_commands
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
ALLOWED_BASE_IMAGES = {
    "ubuntu:${UBUNTU_VERSION}@${UBUNTU_DIGEST}",
    "${BASE_IMAGE}",
}


def _validate_image_sources(instructions: list[str], path: Path) -> None:
    """Reject external build stages that bypass the component inventory."""
    stages: set[str] = set()
    for instruction in instructions:
        from_payload = instruction_payload(instruction, "FROM")
        if from_payload is not None:
            try:
                tokens = shlex.split(from_payload)
            except ValueError as exc:
                raise InventoryError(f"cannot parse FROM instruction in {path}: {from_payload}") from exc
            while tokens and tokens[0].startswith("--"):
                tokens.pop(0)
            if not tokens:
                raise InventoryError(f"FROM instruction has no image in {path}: {from_payload}")
            image = tokens[0]
            if image not in ALLOWED_BASE_IMAGES and image not in stages:
                raise InventoryError(
                    f"external FROM image is not covered by legal discovery in {path}: {image}; "
                    "inventory the image explicitly before copying or redistributing its contents"
                )
            if len(tokens) >= 3 and tokens[-2].upper() == "AS":
                stages.add(tokens[-1])

        copy_payload = instruction_payload(instruction, "COPY")
        if copy_payload is None:
            continue
        match = re.search(r"(?:^|\s)--from(?:=|\s+)([^\s]+)", copy_payload)
        if match is None:
            continue
        source = match.group(1)
        if source not in stages and not source.isdigit():
            raise InventoryError(
                f"external COPY --from source is not covered by legal discovery in {path}: {source}"
            )


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


def _interpreter_network_fetch(tokens: list[str]) -> str | None:
    """Identify inline interpreter fetches that cannot be attributed safely."""
    if not tokens:
        return None
    executable = executable_name(tokens[0])
    text = " ".join(tokens)
    if executable.startswith("python") and "-c" in tokens and re.search(
        r"(?:urllib(?:\.request)?|requests|http\.client|urlopen|https?://)", text, re.I
    ):
        return "Python inline network acquisition"
    if executable == "node" and any(option in tokens for option in {"-e", "--eval"}) and re.search(
        r"(?:\bfetch\s*\(|require\(['\"]https?['\"]\)|https?://)", text, re.I
    ):
        return "Node.js inline network acquisition"
    if executable == "busybox" and len(tokens) > 1 and tokens[1] == "wget":
        return "busybox wget"
    return None


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
    instructions = docker_instructions(path)
    _validate_image_sources(instructions, path)
    for instruction in instructions:
        add_payload = instruction_payload(instruction, "ADD")
        if add_payload is not None:
            if "$" in add_payload:
                raise InventoryError(
                    f"variable-based ADD sources are unsupported by legal discovery in {path}: {add_payload}"
                )
            urls.update(match.group(0).rstrip("),.;") for match in URL_RE.finditer(add_payload))
        for tokens in run_commands(instruction, path):
            if apt_packages_from_command(tokens, path) is not None:
                continue
            text = " ".join(tokens)
            interpreter_fetch = _interpreter_network_fetch(tokens)
            if interpreter_fetch is not None:
                raise InventoryError(f"{interpreter_fetch} is unsupported by legal discovery in {path}: {text}")
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
