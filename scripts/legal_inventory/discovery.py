"""Discovery of package installations and direct-download ownership."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .apt_scan import parse_apt_packages
from .build_scripts import validate_build_scripts
from .download_scan import docker_download_urls, instruction_runs_network_fetch
from .installer_scan import discovered_installer_instructions
from .inventory import inventory_components
from .io import InventoryError
from .npm_scan import global_npm_specs
from .url_match import download_marker_matches, validate_download_marker


def validate_discovery(root: Path, inventory: dict[str, Any]) -> None:
    """Require inventory ownership for discovered downloads and installers."""
    components = inventory_components(inventory)
    dockerfiles = [root / "images/base/Dockerfile", root / "images/codex/Dockerfile"]
    validate_build_scripts(root, dockerfiles)
    marker_claims: list[tuple[str, str]] = []
    for component in components:
        markers = component.get("download_url_markers", [])
        if not isinstance(markers, list):
            raise InventoryError(f"{component['id']} download_url_markers must be an array")
        for marker in markers:
            if not isinstance(marker, str):
                raise InventoryError(f"{component['id']} has invalid download URL marker {marker!r}")
            validate_download_marker(marker)
            marker_claims.append((marker, component["id"]))

    discovered_urls: list[str] = []
    for dockerfile in dockerfiles:
        discovered_urls.extend(docker_download_urls(dockerfile))
    for url in sorted(set(discovered_urls)):
        matches = [(marker, component) for marker, component in marker_claims if download_marker_matches(marker, url)]
        owners = sorted({component for _, component in matches})
        if len(matches) != 1:
            raise InventoryError(
                f"direct-download URL must be claimed by exactly one component ({', '.join(owners) or 'none'}): {url}"
            )
    for marker, component in marker_claims:
        if not any(download_marker_matches(marker, url) for url in discovered_urls):
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
