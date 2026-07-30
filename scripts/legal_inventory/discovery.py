"""Discovery of package installations and direct-download ownership."""
from __future__ import annotations
import re
import shlex
from pathlib import Path
from typing import Any
from .io import InventoryError
from .inventory import inventory_components

URL_RE = re.compile(r"https://[^\s\"'<>]+")

PACKAGE_SPEC_RE = re.compile(r"(?P<name>@?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?)@\$\{(?P<key>[A-Z][A-Z0-9_]*)\}")

NETWORK_FETCH_RE = re.compile(r"\b(?:curl|wget)\b|\bgit\s+clone\b")

SENSITIVE_INSTALL_PATTERNS = (
    re.compile(r"\b(?:pip|pip3)\s+install\b"),
    re.compile(r"\bpython(?:3)?\s+-m\s+pip\s+install\b"),
    re.compile(r"\buv\s+(?:pip|tool)\s+install\b"),
    re.compile(r"\bcargo\s+install\b"),
    re.compile(r"\bgo\s+install\b"),
    re.compile(r"\bgem\s+install\b"),
    re.compile(r"\bcomposer\s+global\s+require\b"),
)

def parse_apt_packages(dockerfile: Path) -> list[str]:
    """Extract the exact direct APT package set from the base Dockerfile."""
    lines = dockerfile.read_text(encoding="utf-8").splitlines()
    packages: list[str] = []
    in_install = False
    for raw in lines:
        stripped = raw.strip()
        if "apt-get install" in stripped and "--no-install-recommends" in stripped:
            if in_install:
                raise InventoryError(f"nested apt install block in {dockerfile}")
            in_install = True
            tail = stripped.split("--no-install-recommends", 1)[1].strip().rstrip("\\").strip()
            if tail:
                for token in tail.split():
                    if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", token):
                        raise InventoryError(
                            f"unsupported APT package token {token!r} in {dockerfile}; "
                            "record direct package names explicitly"
                        )
                    packages.append(token)
            continue
        if not in_install:
            continue
        token_line = stripped.rstrip("\\").strip()
        if token_line.startswith("&&") or token_line.startswith(";"):
            in_install = False
            continue
        if token_line:
            for token in token_line.split():
                if token.startswith("#"):
                    break
                if not re.fullmatch(r"[a-z0-9][a-z0-9+.-]*", token):
                    raise InventoryError(
                        f"unsupported APT package token {token!r} in {dockerfile}; "
                        "record direct package names explicitly"
                    )
                packages.append(token)
        if not stripped.endswith("\\"):
            in_install = False
    normalized = sorted(set(packages))
    if not normalized:
        raise InventoryError(f"no APT packages discovered in {dockerfile}")
    return normalized

def docker_instructions(path: Path) -> list[str]:
    """Join Dockerfile continuation lines into logical instructions."""
    instructions: list[str] = []
    current: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        current.append(stripped.rstrip("\\").strip())
        if stripped.endswith("\\"):
            continue
        instructions.append(" ".join(part for part in current if part))
        current = []
    if current:
        instructions.append(" ".join(part for part in current if part))
    return instructions

def docker_download_urls(path: Path) -> list[str]:
    """Discover literal network sources used by Docker build instructions."""
    urls: list[str] = []
    for instruction in docker_instructions(path):
        is_network_run = instruction.startswith("RUN ") and NETWORK_FETCH_RE.search(instruction)
        is_remote_add = instruction.startswith("ADD ") and URL_RE.search(instruction)
        if not is_network_run and not is_remote_add:
            continue
        discovered = [match.group(0).rstrip("),.;") for match in URL_RE.finditer(instruction)]
        if is_network_run and not discovered:
            raise InventoryError(
                f"network-fetch instruction must contain a literal HTTPS source in {path}: {instruction}"
            )
        urls.extend(discovered)
    return sorted(set(urls))

def global_npm_specs(dockerfile: Path) -> list[tuple[str, str]]:
    """Discover every globally installed npm package/version-key pair."""
    result: set[tuple[str, str]] = set()
    for instruction in docker_instructions(dockerfile):
        if not instruction.startswith("RUN "):
            continue
        for segment in re.split(r"\s*(?:&&|;)\s*", instruction[4:]):
            try:
                tokens = shlex.split(segment)
            except ValueError as exc:
                raise InventoryError(f"cannot parse npm install instruction in {dockerfile}: {segment}") from exc
            if len(tokens) < 3 or tokens[0] != "npm" or tokens[1] not in {"install", "i"}:
                continue
            if "--global" not in tokens and "-g" not in tokens:
                continue
            package_tokens = [token for token in tokens[2:] if not token.startswith("-")]
            if not package_tokens:
                raise InventoryError(f"global npm install has no package spec in {dockerfile}: {segment}")
            for token in package_tokens:
                match = PACKAGE_SPEC_RE.fullmatch(token)
                if not match:
                    raise InventoryError(
                        f"unsupported global npm package spec {token!r} in {dockerfile}; "
                        "pin it through versions.env as package@${VERSION_KEY}"
                    )
                result.add((match.group("name"), match.group("key")))
    return sorted(result)

def discovered_installer_instructions(dockerfile: Path) -> list[str]:
    """Find installer commands that need an explicit inventory marker."""
    result: list[str] = []
    for instruction in docker_instructions(dockerfile):
        if not instruction.startswith("RUN "):
            continue
        if any(pattern.search(instruction) for pattern in SENSITIVE_INSTALL_PATTERNS):
            result.append(instruction)
    return sorted(set(result))

def validate_discovery(root: Path, inventory: dict[str, Any]) -> None:
    """Require inventory ownership for discovered downloads and installers."""
    components = inventory_components(inventory)
    marker_claims: list[tuple[str, str]] = []
    for component in components:
        markers = component.get("download_url_markers", [])
        if not isinstance(markers, list):
            raise InventoryError(f"{component['id']} download_url_markers must be an array")
        for marker in markers:
            if not isinstance(marker, str) or not marker.startswith("https://"):
                raise InventoryError(f"{component['id']} has invalid download URL marker {marker!r}")
            marker_claims.append((marker, component["id"]))

    discovered_urls: list[str] = []
    for relative in ("images/base/Dockerfile", "images/codex/Dockerfile"):
        discovered_urls.extend(docker_download_urls(root / relative))
    for url in sorted(set(discovered_urls)):
        owners = sorted({component for marker, component in marker_claims if marker in url})
        if len(owners) != 1:
            raise InventoryError(
                f"direct-download URL must be claimed by exactly one component ({', '.join(owners) or 'none'}): {url}"
            )
    for marker, component in marker_claims:
        if not any(marker in url for url in discovered_urls):
            raise InventoryError(f"{component} claims unused download URL marker: {marker}")

    installer_markers: list[tuple[str, str]] = []
    for component in components:
        markers = component.get("install_command_markers", [])
        if not isinstance(markers, list):
            raise InventoryError(f"{component['id']} install_command_markers must be an array")
        for marker in markers:
            if not isinstance(marker, str) or not marker.strip():
                raise InventoryError(f"{component['id']} has invalid install command marker {marker!r}")
            installer_markers.append((marker, component["id"]))

    installer_instructions: list[str] = []
    for relative in ("images/base/Dockerfile", "images/codex/Dockerfile"):
        installer_instructions.extend(discovered_installer_instructions(root / relative))
    for instruction in installer_instructions:
        owners = sorted({component for marker, component in installer_markers if marker in instruction})
        if len(owners) != 1:
            raise InventoryError(
                "installer command must be claimed by exactly one component "
                f"({', '.join(owners) or 'none'}): {instruction}"
            )
    for marker, component in installer_markers:
        if not any(marker in instruction for instruction in installer_instructions):
            raise InventoryError(f"{component} claims unused install command marker: {marker}")

    npm_claims: dict[tuple[str, str], str] = {}
    for component in components:
        npm_global = component.get("npm_global")
        if npm_global is None:
            continue
        if not isinstance(npm_global, dict):
            raise InventoryError(f"{component['id']} npm_global must be an object")
        pair = (npm_global.get("package"), npm_global.get("version_key"))
        if not all(isinstance(item, str) and item for item in pair):
            raise InventoryError(f"{component['id']} has invalid npm_global declaration")
        if pair in npm_claims:
            raise InventoryError(f"global npm package {pair[0]} is claimed more than once")
        npm_claims[pair] = component["id"]
    discovered_npm = set(global_npm_specs(root / "images/base/Dockerfile")) | set(
        global_npm_specs(root / "images/codex/Dockerfile")
    )
    if discovered_npm != set(npm_claims):
        missing = sorted(discovered_npm - set(npm_claims))
        stale = sorted(set(npm_claims) - discovered_npm)
        details = []
        if missing:
            details.append("unclaimed=" + ", ".join(f"{name}@${{{key}}}" for name, key in missing))
        if stale:
            details.append("stale=" + ", ".join(f"{name}@${{{key}}}" for name, key in stale))
        raise InventoryError("global npm package inventory mismatch: " + "; ".join(details))
