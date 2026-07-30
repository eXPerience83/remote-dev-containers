"""Machine-readable component schema and version-source reconciliation."""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any
from .io import SCHEMA_VERSION, InventoryError, SourceDocument, VERSION_KEY_RE, read_docker_args

def inventory_components(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Return validated, uniquely identified component objects."""
    components = inventory.get("components")
    if not isinstance(components, list) or not components:
        raise InventoryError("inventory components must be a non-empty array")
    seen: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise InventoryError("every component must be an object")
        component_id = component.get("id")
        if not isinstance(component_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", component_id):
            raise InventoryError(f"invalid component id: {component_id!r}")
        if component_id in seen:
            raise InventoryError(f"duplicate component id: {component_id}")
        seen.add(component_id)
    return components

def resolve_component_version(component: dict[str, Any], env: dict[str, str], mise: dict[str, dict[str, Any]]) -> str:
    """Resolve a component version from its declared source."""
    source = component.get("version_source")
    if not isinstance(source, dict):
        raise InventoryError(f"{component['id']} has no version_source object")
    kind = source.get("kind")
    if kind == "env":
        key = source.get("key")
        if not isinstance(key, str) or key not in env:
            raise InventoryError(f"{component['id']} references missing environment version key {key!r}")
        return env[key]
    if kind == "mise":
        tool = source.get("tool")
        if not isinstance(tool, str) or tool not in mise:
            raise InventoryError(f"{component['id']} references missing mise tool {tool!r}")
        version = mise[tool].get("version")
        if not isinstance(version, str) or not version:
            raise InventoryError(f"mise tool {tool} has no version")
        return version
    if kind == "project":
        key = source.get("key")
        if isinstance(key, str) and key in env:
            return env[key]
        return "repository revision"
    if kind == "discovered":
        return "discovered from build recipe"
    raise InventoryError(f"{component['id']} has unsupported version_source kind {kind!r}")

def expected_source_documents(
    inventory: dict[str, Any], env: dict[str, str], mise: dict[str, dict[str, Any]]
) -> list[SourceDocument]:
    """Expand source-document URL templates for selected versions."""
    result: list[SourceDocument] = []
    for component in inventory_components(inventory):
        version = resolve_component_version(component, env, mise)
        documents = component.get("source_documents", [])
        if not isinstance(documents, list):
            raise InventoryError(f"{component['id']} source_documents must be an array")
        for document in documents:
            if not isinstance(document, dict):
                raise InventoryError(f"{component['id']} source document must be an object")
            path = document.get("path")
            template = document.get("url_template")
            if not isinstance(path, str) or not path.startswith("third_party/components/"):
                raise InventoryError(f"{component['id']} has invalid source document path {path!r}")
            if not isinstance(template, str) or "{version}" not in template:
                raise InventoryError(f"{component['id']} source URL must contain {{version}}")
            result.append(SourceDocument(component["id"], path, template.format(version=version), version))
    return result

def validate_schema(inventory: dict[str, Any]) -> None:
    """Validate required inventory fields and closed enumerations."""
    if inventory.get("schema_version") != SCHEMA_VERSION:
        raise InventoryError(
            f"unsupported inventory schema {inventory.get('schema_version')!r}; expected {SCHEMA_VERSION}"
        )
    components = inventory_components(inventory)
    required_fields = {
        "name",
        "distribution",
        "image_scope",
        "version_source",
        "upstream",
        "license_expression",
        "notice_treatment",
        "notice_locations",
        "trademark_policy",
        "sbom",
    }
    for component in components:
        missing = sorted(required_fields - component.keys())
        if missing:
            raise InventoryError(f"{component['id']} is missing fields: {', '.join(missing)}")
        if component["image_scope"] not in {"base", "final", "both", "project", "optional"}:
            raise InventoryError(f"{component['id']} has invalid image_scope")
        locations = component["notice_locations"]
        if not isinstance(locations, list) or not locations or not all(isinstance(x, str) and x for x in locations):
            raise InventoryError(f"{component['id']} notice_locations must be a non-empty string array")
        sbom = component["sbom"]
        if not isinstance(sbom, dict) or sbom.get("status") not in {
            "required",
            "covered-by-ecosystem",
            "not-guaranteed",
            "not-applicable",
        }:
            raise InventoryError(f"{component['id']} has invalid sbom status")
        if sbom.get("status") in {"not-guaranteed", "not-applicable"} and not sbom.get("reason"):
            raise InventoryError(f"{component['id']} must explain why SBOM detection is not required")

def validate_inputs(
    root: Path,
    inventory: dict[str, Any],
    env: dict[str, str],
    mise: dict[str, dict[str, Any]],
) -> None:
    """Reconcile version manifests, Docker ARGs and mise lock entries."""
    components = inventory_components(inventory)
    claims: dict[str, str] = {}
    for component in components:
        inputs = component.get("inputs", [])
        if not isinstance(inputs, list):
            raise InventoryError(f"{component['id']} inputs must be an array")
        for key in inputs:
            if not isinstance(key, str) or not VERSION_KEY_RE.fullmatch(key):
                raise InventoryError(f"{component['id']} has invalid version input {key!r}")
            if key in claims:
                raise InventoryError(f"version input {key} is claimed by both {claims[key]} and {component['id']}")
            claims[key] = component["id"]

    version_inputs = {key for key in env if VERSION_KEY_RE.fullmatch(key)}
    missing = sorted(version_inputs - claims.keys())
    stale = sorted(claims.keys() - version_inputs)
    if missing:
        raise InventoryError(f"versions.env inputs are not inventoried: {', '.join(missing)}")
    if stale:
        raise InventoryError(f"inventory claims missing versions.env inputs: {', '.join(stale)}")

    dockerfiles = [root / "images/base/Dockerfile", root / "images/codex/Dockerfile"]
    docker_args: dict[str, str] = {}
    for dockerfile in dockerfiles:
        for key, value in read_docker_args(dockerfile).items():
            if VERSION_KEY_RE.fullmatch(key):
                if key in docker_args and docker_args[key] != value:
                    raise InventoryError(f"Docker ARG {key} has conflicting defaults")
                docker_args[key] = value
    aliases = inventory.get("docker_arg_aliases", {})
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items()):
        raise InventoryError("docker_arg_aliases must be a string-to-string object")
    claimed_docker_args = set(claims) | set(aliases)
    missing_args = sorted(set(docker_args) - claimed_docker_args)
    if missing_args:
        raise InventoryError(f"Docker version/checksum arguments are not inventoried: {', '.join(missing_args)}")
    for key, value in sorted(docker_args.items()):
        env_key = aliases.get(key, key)
        if env_key in env and value != env[env_key]:
            raise InventoryError(f"Docker ARG {key} disagrees with versions.env {env_key}: {value} != {env[env_key]}")
    stale_aliases = sorted(set(aliases) - set(docker_args))
    if stale_aliases:
        raise InventoryError(f"docker_arg_aliases references missing Docker ARGs: {', '.join(stale_aliases)}")
    invalid_alias_targets = sorted({value for value in aliases.values() if value not in claims})
    if invalid_alias_targets:
        raise InventoryError(f"docker_arg_aliases targets unclaimed inputs: {', '.join(invalid_alias_targets)}")

    mise_claims: dict[str, str] = {}
    for component in components:
        source = component.get("version_source")
        if isinstance(source, dict) and source.get("kind") == "mise":
            tool = source.get("tool")
            if not isinstance(tool, str):
                raise InventoryError(f"{component['id']} has invalid mise tool")
            if tool in mise_claims:
                raise InventoryError(f"mise tool {tool} claimed by multiple components")
            mise_claims[tool] = component["id"]
    unclaimed_mise = sorted(set(mise) - set(mise_claims))
    stale_mise = sorted(set(mise_claims) - set(mise))
    if unclaimed_mise:
        raise InventoryError(f"mise.lock tools are not inventoried: {', '.join(unclaimed_mise)}")
    if stale_mise:
        raise InventoryError(f"inventory claims missing mise tools: {', '.join(stale_mise)}")
    for component in components:
        source = component.get("version_source")
        if isinstance(source, dict) and source.get("kind") == "mise":
            key = source.get("mirror_env_key")
            if isinstance(key, str):
                version = resolve_component_version(component, env, mise)
                if env.get(key) != version:
                    raise InventoryError(f"{component['id']} {key} disagrees with mise.lock: {env.get(key)} != {version}")
