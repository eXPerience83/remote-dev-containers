"""Command-line orchestration for legal inventory maintenance."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .discovery import validate_discovery
from .documents import (
    refresh_sources,
    render_readme,
    validate_optional_policy,
    validate_rendered_readme,
    validate_sources,
)
from .inventory import validate_inputs, validate_schema
from .io import InventoryError, load_json, read_env, read_mise_lock
from .sbom import reconcile_sboms


def validate(root: Path) -> None:
    """Run the complete repository legal-inventory validation."""
    inventory = load_json(root / "third_party/inventory.json")
    validate_schema(inventory)
    env = read_env(root / "versions.env")
    mise = read_mise_lock(root / "mise.lock")
    validate_inputs(root, inventory, env, mise)
    validate_discovery(root, inventory)
    validate_sources(root, inventory, env, mise)
    validate_rendered_readme(root, inventory, env, mise)
    validate_optional_policy(root)
    print("Third-party legal inventory: OK")


def main(argv: list[str] | None = None) -> int:
    """Dispatch inventory validation, rendering, refresh and SBOM reconciliation."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent.parent)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    subparsers.add_parser("render")
    subparsers.add_parser("refresh")
    reconcile = subparsers.add_parser("reconcile-sbom")
    reconcile.add_argument("--sbom", action="append", default=[])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        inventory = load_json(root / "third_party/inventory.json")
        validate_schema(inventory)
        env = read_env(root / "versions.env")
        mise = read_mise_lock(root / "mise.lock")
        if args.command == "validate":
            validate(root)
        elif args.command == "render":
            output = render_readme(root, inventory, env, mise)
            (root / "third_party/README.md").write_text(output, encoding="utf-8")
            print("rendered third_party/README.md")
        elif args.command == "refresh":
            refresh_sources(root, inventory, env, mise)
            output = render_readme(root, inventory, env, mise)
            (root / "third_party/README.md").write_text(output, encoding="utf-8")
            print("rendered third_party/README.md")
        elif args.command == "reconcile-sbom":
            reconcile_sboms(root, inventory, args.sbom)
        else:  # pragma: no cover
            raise InventoryError(f"unsupported command: {args.command}")
    except InventoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0
