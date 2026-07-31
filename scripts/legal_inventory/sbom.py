"""SPDX package-URL reconciliation against declared inventory coverage."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .discovery import parse_apt_packages
from .io import InventoryError, load_json


def purl_type(locator: str) -> str | None:
    """Extract the package-url type from a purl."""
    if not locator.startswith("pkg:"):
        return None
    value = locator[4:].split("/", 1)[0]
    return value or None


def purl_name(locator: str) -> str | None:
    """Extract and decode the package name from a purl."""
    if not locator.startswith("pkg:") or "/" not in locator[4:]:
        return None
    body = locator[4:].split("/", 1)[1]
    body = body.split("?", 1)[0].split("#", 1)[0].split("@", 1)[0]
    name = body.rsplit("/", 1)[-1]
    return unquote(name) if name else None


def spdx_packages(path: Path) -> list[dict[str, Any]]:
    """Load package objects from an SPDX JSON document."""
    data = load_json(path)
    packages = data.get("packages")
    if not isinstance(packages, list):
        raise InventoryError(f"SPDX document has no packages array: {path}")
    return [package for package in packages if isinstance(package, dict)]


def package_purls(package: dict[str, Any]) -> set[str]:
    """Return all package URLs attached to an SPDX package."""
    result: set[str] = set()
    for ref in package.get("externalRefs", []) or []:
        if not isinstance(ref, dict):
            continue
        locator = ref.get("referenceLocator")
        if isinstance(locator, str) and locator.startswith("pkg:"):
            result.add(locator)
    return result


def reconcile_sboms(root: Path, inventory: dict[str, Any], named_paths: list[str]) -> None:
    """Compare generated image SPDX inventories with declared coverage."""
    if not named_paths:
        raise InventoryError("at least one --sbom scope=path value is required")
    coverage = inventory.get("sbom_coverage")
    if not isinstance(coverage, list) or not coverage:
        raise InventoryError("inventory sbom_coverage must be a non-empty array")
    covered_types: dict[str, str] = {}
    for rule in coverage:
        if not isinstance(rule, dict):
            raise InventoryError("SBOM coverage rule must be an object")
        owner = rule.get("owner")
        types = rule.get("purl_types")
        if not isinstance(owner, str) or not owner or not isinstance(types, list):
            raise InventoryError("invalid SBOM coverage rule")
        for value in types:
            if not isinstance(value, str) or not value:
                raise InventoryError("invalid SBOM purl type")
            if value in covered_types:
                raise InventoryError(f"SBOM purl type {value} is covered more than once")
            covered_types[value] = owner

    parsed_paths: dict[str, Path] = {}
    for item in named_paths:
        if "=" not in item:
            raise InventoryError(f"invalid --sbom value {item!r}; expected scope=path")
        scope, raw_path = item.split("=", 1)
        if scope not in {"base", "final"} or not raw_path:
            raise InventoryError(f"invalid SBOM scope/path: {item!r}")
        if scope in parsed_paths:
            raise InventoryError(f"duplicate SBOM scope: {scope}")
        parsed_paths[scope] = Path(raw_path)
    if set(parsed_paths) != {"base", "final"}:
        raise InventoryError("SBOM reconciliation requires exactly base and final documents")

    apt_packages = set(parse_apt_packages(root / "images/base/Dockerfile"))
    scope_purls: dict[str, set[str]] = {}
    for scope, sbom_path in sorted(parsed_paths.items()):
        packages = spdx_packages(sbom_path)
        seen_types: set[str] = set()
        deb_names: set[str] = set()
        purls: set[str] = set()
        for package in packages:
            for purl in package_purls(package):
                purls.add(purl)
                kind = purl_type(purl)
                if kind:
                    seen_types.add(kind)
                if kind == "deb":
                    name = purl_name(purl)
                    if name:
                        deb_names.add(name)
        unknown = sorted(seen_types - set(covered_types))
        if unknown:
            raise InventoryError(
                f"{scope} SBOM contains unclassified package ecosystems: {', '.join(unknown)}; add sbom_coverage"
            )
        missing_apt = sorted(apt_packages - deb_names)
        if missing_apt:
            raise InventoryError(f"{scope} SBOM is missing directly installed APT packages: {', '.join(missing_apt)}")
        if not seen_types:
            raise InventoryError(f"{scope} SBOM contains no package URLs")
        scope_purls[scope] = purls
        print(f"{scope} SBOM reconciled: {len(packages)} packages, ecosystems={','.join(sorted(seen_types))}")

    missing_from_final = sorted(scope_purls["base"] - scope_purls["final"])
    if missing_from_final:
        preview = ", ".join(missing_from_final[:10])
        suffix = " ..." if len(missing_from_final) > 10 else ""
        raise InventoryError("final SBOM is missing packages from the base image: " + preview + suffix)
