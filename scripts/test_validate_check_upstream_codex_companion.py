#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_validator(root: Path):
    module_path = root / "scripts" / "validate-check-upstream-codex-companion.py"
    spec = importlib.util.spec_from_file_location("validate_check_upstream_codex_companion", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load validator from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_failure(module, text: str, label: str) -> None:
    try:
        module.validate_text(text)
    except module.ValidationError:
        return
    raise AssertionError(f"validator accepted invalid fixture: {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()

    module = load_validator(root)
    workflow = root / ".github" / "workflows" / "check-upstream.yml"
    text = workflow.read_text(encoding="utf-8")

    module.validate_text(text)

    active_env = (
        '          replace_env CODEX_CODE_MODE_HOST_AMD64_SHA256 '
        '"$codex_code_mode_host_amd64_sha256"'
    )
    commented_env = (
        '          # replace_env CODEX_CODE_MODE_HOST_AMD64_SHA256 '
        '"$codex_code_mode_host_amd64_sha256"'
    )
    if active_env not in text:
        raise AssertionError("test fixture could not find active AMD64 companion env update")
    expect_failure(
        module,
        text.replace(active_env, commented_env, 1),
        "commented companion update",
    )

    amd64_resolution = (
        '          codex_code_mode_host_amd64_sha256="$(release_sha256 '
        '"$workdir/codex.json" codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz)"'
    )
    swapped_resolution = (
        '          codex_code_mode_host_amd64_sha256="$(release_sha256 '
        '"$workdir/codex.json" codex-code-mode-host-aarch64-unknown-linux-musl.tar.gz)"'
    )
    if amd64_resolution not in text:
        raise AssertionError("test fixture could not find AMD64 companion digest assignment")
    expect_failure(
        module,
        text.replace(amd64_resolution, swapped_resolution, 1),
        "swapped AMD64/ARM64 companion digest assignment",
    )

    print("Codex companion updater validator regression fixtures passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
