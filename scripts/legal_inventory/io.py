"""Deterministic file, manifest and Git-object helpers."""
from __future__ import annotations
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

VERSION_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:VERSION|RELEASE_TAG|DIGEST|SHA256)$")

ENV_ASSIGN_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")

ARG_ASSIGN_RE = re.compile(r"^\s*ARG\s+([A-Z][A-Z0-9_]*)(?:=(.*))?\s*$")

class InventoryError(RuntimeError):
    pass

@dataclass(frozen=True)
class SourceDocument:
    component_id: str
    path: str
    url: str
    version: str

def load_json(path: Path) -> dict[str, Any]:
    """Load and type-check a JSON object from disk."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InventoryError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InventoryError(f"expected a JSON object in {path}")
    return data

def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write deterministic, newline-terminated JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def read_env(path: Path) -> dict[str, str]:
    """Parse the repository key-value version manifest."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise InventoryError(f"required file is missing: {path}") from exc
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_ASSIGN_RE.match(line)
        if not match:
            raise InventoryError(f"invalid assignment at {path}:{number}: {raw}")
        key, value = match.groups()
        if key in values:
            raise InventoryError(f"duplicate {key} in {path}")
        if not value:
            raise InventoryError(f"empty {key} in {path}")
        values[key] = value
    return values

def read_docker_args(path: Path) -> dict[str, str]:
    """Read Docker ARG defaults while rejecting conflicting definitions."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = ARG_ASSIGN_RE.match(raw)
        if not match:
            continue
        key, value = match.groups()
        if value is None:
            continue
        if key in values and values[key] != value:
            raise InventoryError(f"conflicting ARG {key} defaults in {path}:{number}")
        values[key] = value
    return values

def read_mise_lock(path: Path) -> dict[str, dict[str, Any]]:
    """Load exactly one locked entry for every mise tool."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        raise InventoryError(f"cannot parse {path}: {exc}") from exc
    tools = data.get("tools")
    if not isinstance(tools, dict) or not tools:
        raise InventoryError(f"{path} contains no locked tools")
    normalized: dict[str, dict[str, Any]] = {}
    for name, entries in tools.items():
        if not isinstance(entries, list) or len(entries) != 1 or not isinstance(entries[0], dict):
            raise InventoryError(f"{path} must contain exactly one [[tools.{name}]] entry")
        normalized[name] = entries[0]
    return normalized

def git_blob_sha1(data: bytes) -> str:
    """Return the canonical Git blob identity for content bytes."""
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()
