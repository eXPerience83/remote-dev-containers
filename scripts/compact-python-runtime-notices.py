#!/usr/bin/env python3
"""Normalize Python standalone metadata to its reviewable legal subset."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn


SYNC_SCRIPT = Path(__file__).with_name("sync-python-runtime-notices.py")


def fail(message: str) -> NoReturn:
    """Exit with a consistent validation error."""
    raise SystemExit(f"ERROR: {message}")


def load_synchronizer() -> ModuleType:
    """Load the bounded synchronizer without renaming its CLI file."""
    spec = importlib.util.spec_from_file_location("python_runtime_notice_sync", SYNC_SCRIPT)
    if spec is None or spec.loader is None:
        fail(f"cannot load {SYNC_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def string_list(value: Any, description: str) -> list[str]:
    """Validate and return a stable unique list of strings."""
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{description} must be an array of strings")
    return sorted(set(value))


def build_legal_summary(metadata: dict[str, Any], sync: ModuleType) -> dict[str, Any]:
    """Retain only version, target and license relationships from PYTHON.json."""
    extensions: dict[str, list[dict[str, list[str]]]] = {}
    build_info = metadata.get("build_info")
    raw_extensions = build_info.get("extensions") if isinstance(build_info, dict) else None
    if raw_extensions is not None and not isinstance(raw_extensions, dict):
        fail("PYTHON.json build_info.extensions must be an object")

    for name, variants in sorted((raw_extensions or {}).items()):
        if not isinstance(name, str) or not isinstance(variants, list):
            fail("PYTHON.json extension records are malformed")
        legal_variants: list[dict[str, list[str]]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                fail(f"PYTHON.json extension variant is malformed: {name}")
            licenses = string_list(variant.get("licenses"), f"{name} licenses")
            license_paths = string_list(
                variant.get("license_paths"), f"{name} license_paths"
            )
            if licenses or license_paths:
                legal_variants.append(
                    {"licenses": licenses, "license_paths": license_paths}
                )
        if legal_variants:
            extensions[name] = legal_variants

    python_version = metadata.get("python_version")
    target_triple = metadata.get("target_triple")
    implementation_path = metadata.get("license_path")
    if not isinstance(python_version, str) or not python_version:
        fail("PYTHON.json has no python_version")
    if not isinstance(target_triple, str) or not target_triple:
        fail("PYTHON.json has no target_triple")
    if not isinstance(implementation_path, str) or not implementation_path:
        fail("PYTHON.json has no implementation license_path")

    return {
        "schema_version": 1,
        "python_version": python_version,
        "target_triple": target_triple,
        "implementation_licenses": string_list(
            metadata.get("licenses"), "implementation licenses"
        ),
        "implementation_license_path": implementation_path,
        "referenced_license_paths": sorted(sync.referenced_license_paths(metadata)),
        "extensions": extensions,
    }


def write_json(path: Path, value: Any) -> None:
    """Write deterministic UTF-8 JSON."""
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def compact(output: Path, sync: ModuleType) -> None:
    """Replace raw PYTHON.json files with compact legal summaries."""
    for arch in ("amd64", "arm64"):
        arch_root = output / arch
        raw_path = arch_root / "PYTHON.json"
        compact_path = arch_root / "license-metadata.json"
        if raw_path.is_file():
            try:
                metadata = json.loads(raw_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                fail(f"cannot read valid {raw_path}: {exc}")
            if not isinstance(metadata, dict):
                fail(f"{raw_path} must contain an object")
            write_json(compact_path, build_legal_summary(metadata, sync))
            raw_path.unlink()
        elif not compact_path.is_file():
            fail(f"neither raw nor compact Python metadata exists for {arch}")


def safe_preserved_path(output: Path, relative: str) -> Path:
    """Resolve one metadata path and keep it inside the generated directory."""
    base = output.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        fail(f"Python notice path escapes the preserved directory: {relative}")
    return candidate


def check(root: Path, output: Path, sync: ModuleType) -> None:
    """Validate compact metadata and shared licenses against mise.lock."""
    expected_records = sync.parse_install_artifacts(root / "mise.lock")
    manifest_path = output / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid {manifest_path}: {exc}")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        fail(f"unsupported Python notice manifest: {manifest_path}")
    if manifest.get("shared_license_texts") is not True:
        fail("Python notice manifest must declare shared license texts")

    records = manifest.get("artifacts")
    if not isinstance(records, list):
        fail("Python notice manifest has no artifacts array")
    by_arch = {
        record.get("arch"): record
        for record in records
        if isinstance(record, dict) and isinstance(record.get("arch"), str)
    }
    if set(by_arch) != {"amd64", "arm64"}:
        fail("Python notice manifest must contain exactly amd64 and arm64")

    for expected in expected_records:
        actual = by_arch[expected["arch"]]
        for key in ("target", "python_version", "release", "install_asset_url"):
            if actual.get(key) != expected[key]:
                fail(f"Python notice manifest mismatch for {expected['arch']} {key}")
        digest = actual.get("full_asset_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail(f"Python notice manifest has no valid digest for {expected['arch']}")

        metadata_path = output / expected["arch"] / "license-metadata.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"cannot read valid {metadata_path}: {exc}")
        if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
            fail(f"unsupported compact Python metadata: {metadata_path}")
        if metadata.get("python_version") != expected["python_version"]:
            fail(f"Python metadata version mismatch for {expected['arch']}")
        if metadata.get("target_triple") != expected["target"]:
            fail(f"Python metadata target mismatch for {expected['arch']}")
        paths = metadata.get("referenced_license_paths")
        if not isinstance(paths, list) or not paths or not all(
            isinstance(item, str) for item in paths
        ):
            fail(f"Python metadata has no valid license path list for {expected['arch']}")
        for relative in paths:
            if not relative.startswith("licenses/") or ".." in Path(relative).parts:
                fail(f"unsafe compact Python license path: {relative}")
            license_path = safe_preserved_path(output, relative)
            if not license_path.is_file() or license_path.stat().st_size == 0:
                fail(f"missing Python license text for {expected['arch']}: {relative}")
        if (output / expected["arch"] / "PYTHON.json").exists():
            fail(f"raw PYTHON.json must not be committed for {expected['arch']}")

    supplemental = manifest.get("supplemental_licenses")
    if not isinstance(supplemental, list):
        fail("Python notice manifest has no supplemental_licenses array")
    expected_supplemental = {
        (path, entry["url"], entry["sha256"])
        for path, entry in sync.SUPPLEMENTAL_LICENSES.items()
    }
    actual_supplemental: set[tuple[str, str, str]] = set()
    for entry in supplemental:
        if not isinstance(entry, dict):
            fail("Python supplemental license record must be an object")
        path = entry.get("path")
        url = entry.get("source_url")
        digest = entry.get("sha256")
        if not all(isinstance(value, str) for value in (path, url, digest)):
            fail("Python supplemental license record is malformed")
        actual_supplemental.add((path, url, digest))
        content = safe_preserved_path(output, path).read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()
        if actual_digest != digest:
            fail(f"supplemental Python license digest mismatch: {path}")
    if actual_supplemental != expected_supplemental:
        fail("Python supplemental license sources do not match the reviewed mapping")

    print("Compact Python standalone runtime notices: OK")


def main() -> None:
    """Compact or validate the Python runtime legal metadata."""
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    output = (
        args.output.resolve()
        if args.output
        else root / "third_party" / "components" / "python-build-standalone"
    )
    sync = load_synchronizer()
    if args.write:
        compact(output, sync)
    check(root, output, sync)


if __name__ == "__main__":
    main()
