#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


class ValidationError(RuntimeError):
    pass


RESOLUTION_EXPECTED = (
    'codex_amd64_sha256="$(release_sha256 "$workdir/codex.json" codex-x86_64-unknown-linux-musl.tar.gz)"',
    'codex_arm64_sha256="$(release_sha256 "$workdir/codex.json" codex-aarch64-unknown-linux-musl.tar.gz)"',
    'codex_code_mode_host_amd64_sha256="$(release_sha256 "$workdir/codex.json" codex-code-mode-host-x86_64-unknown-linux-musl.tar.gz)"',
    'codex_code_mode_host_arm64_sha256="$(release_sha256 "$workdir/codex.json" codex-code-mode-host-aarch64-unknown-linux-musl.tar.gz)"',
)
ENV_EXPECTED = (
    'replace_env CODEX_RELEASE_TAG "$latest_codex"',
    'replace_env CODEX_AMD64_SHA256 "$codex_amd64_sha256"',
    'replace_env CODEX_ARM64_SHA256 "$codex_arm64_sha256"',
    'replace_env CODEX_CODE_MODE_HOST_AMD64_SHA256 "$codex_code_mode_host_amd64_sha256"',
    'replace_env CODEX_CODE_MODE_HOST_ARM64_SHA256 "$codex_code_mode_host_arm64_sha256"',
)
DOCKERFILE_EXPECTED = (
    'replace_arg images/codex/Dockerfile CODEX_RELEASE_TAG "$latest_codex"',
    'replace_arg images/codex/Dockerfile CODEX_AMD64_SHA256 "$codex_amd64_sha256"',
    'replace_arg images/codex/Dockerfile CODEX_ARM64_SHA256 "$codex_arm64_sha256"',
    'replace_arg images/codex/Dockerfile CODEX_CODE_MODE_HOST_AMD64_SHA256 "$codex_code_mode_host_amd64_sha256"',
    'replace_arg images/codex/Dockerfile CODEX_CODE_MODE_HOST_ARM64_SHA256 "$codex_code_mode_host_arm64_sha256"',
)


def bounded_block(
    lines: list[str],
    *,
    start_prefix: str,
    end_prefix: str,
    label: str,
) -> list[str]:
    starts = [index for index, line in enumerate(lines) if line.strip().startswith(start_prefix)]
    if len(starts) != 1:
        raise ValidationError(f"{label}: expected exactly one start marker {start_prefix!r}")

    start = starts[0]
    ends = [
        index
        for index in range(start + 1, len(lines))
        if lines[index].strip().startswith(end_prefix)
    ]
    if not ends:
        raise ValidationError(f"{label}: missing end marker {end_prefix!r}")

    end = ends[0]
    return lines[start:end]


def require_exact_block(block: list[str], expected: tuple[str, ...], label: str) -> None:
    normalized = [line.strip() for line in block if line.strip()]
    if normalized != list(expected):
        expected_text = "\n  ".join(expected)
        actual_text = "\n  ".join(normalized) if normalized else "<empty>"
        raise ValidationError(
            f"{label}: updater contract changed\n"
            f"Expected:\n  {expected_text}\n"
            f"Actual:\n  {actual_text}"
        )


def validate_text(text: str) -> None:
    lines = text.splitlines()

    resolution = bounded_block(
        lines,
        start_prefix="codex_amd64_sha256=",
        end_prefix="gh_amd64_sha256=",
        label="Codex release digest block",
    )
    require_exact_block(resolution, RESOLUTION_EXPECTED, "Codex release digest block")

    env_updates = bounded_block(
        lines,
        start_prefix="replace_env CODEX_RELEASE_TAG ",
        end_prefix="replace_env GH_VERSION ",
        label="Codex versions.env update block",
    )
    require_exact_block(env_updates, ENV_EXPECTED, "Codex versions.env update block")

    dockerfile_updates = bounded_block(
        lines,
        start_prefix="replace_arg images/codex/Dockerfile CODEX_RELEASE_TAG ",
        end_prefix="replace_arg images/base/Dockerfile GH_VERSION ",
        label="Codex Dockerfile update block",
    )
    require_exact_block(
        dockerfile_updates,
        DOCKERFILE_EXPECTED,
        "Codex Dockerfile update block",
    )


def validate(root: Path) -> None:
    workflow = root / ".github" / "workflows" / "check-upstream.yml"
    try:
        text = workflow.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"could not read {workflow}: {exc}") from exc
    validate_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate complete Codex Code Mode companion pin updates in check-upstream.yml."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()

    try:
        validate(args.root.resolve())
    except ValidationError as exc:
        print(f"ERROR: {exc}")
        return 1

    print("Codex upstream updater keeps AMD64/ARM64 Code Mode host pins bound correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
