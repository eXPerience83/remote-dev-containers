"""Discovery of globally installed npm packages."""
from __future__ import annotations

import re
from pathlib import Path

from .docker_parse import docker_instructions, executable_name, run_commands, strip_command_prefix
from .io import InventoryError

PACKAGE_SPEC_RE = re.compile(
    r"(?P<name>@?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)@\$\{(?P<key>[A-Z][A-Z0-9_]*)\}"
)
NPM_INSTALL_ALIASES = {
    # npm install
    "add",
    "i",
    "in",
    "ins",
    "inst",
    "insta",
    "instal",
    "install",
    "isnt",
    "isnta",
    "isntal",
    "isntall",
    # npm ci
    "ci",
    "clean-install",
    "ic",
    "install-clean",
    "isntall-clean",
    # npm install-test
    "install-test",
    "it",
    # npm install-ci-test
    "cit",
    "clean-install-test",
    "install-ci-test",
    "sit",
}
NPM_VALUE_OPTIONS = {
    "--cache",
    "--prefix",
    "--registry",
    "--userconfig",
    "--workspace",
    "-w",
    "--location",
}


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
            if index < len(tokens) and subcommand_index is None:
                subcommand_index = index
            break
        if token in {"-g", "--global", "--location=global"}:
            global_mode = True
            index += 1
            continue
        if token.startswith("--location="):
            global_mode = token.split("=", 1)[1] == "global"
            index += 1
            continue
        if token in NPM_VALUE_OPTIONS:
            if index + 1 >= len(tokens):
                raise InventoryError(f"npm option {token} has no value in {path}")
            if token == "--location":
                global_mode = tokens[index + 1] == "global"
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        subcommand_index = index
        break

    if subcommand_index is None or tokens[subcommand_index] not in NPM_INSTALL_ALIASES:
        return None

    index = subcommand_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-g", "--global", "--location=global"}:
            global_mode = True
            index += 1
        elif token.startswith("--location="):
            global_mode = token.split("=", 1)[1] == "global"
            index += 1
        elif token in NPM_VALUE_OPTIONS:
            if index + 1 >= len(tokens):
                raise InventoryError(f"npm option {token} has no value in {path}")
            if token == "--location":
                global_mode = tokens[index + 1] == "global"
            index += 2
        else:
            index += 1
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
                    package_tokens.extend(tokens[index + 1 :])
                    break
                if token in NPM_VALUE_OPTIONS:
                    index += 2
                    continue
                if token.startswith("--location=") or token.startswith("-"):
                    index += 1
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
