#!/usr/bin/env python3
"""Preserve FFmpeg legal evidence emitted by the exact SHA-256-pinned binary.

Run only during the image build in a network-disabled BuildKit RUN step.
The license and build configuration are obtained from the installed binary,
because Playwright's published FFmpeg 1013 ZIP has no separate license file.
The periodic read-only updater never executes this binary.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

MANIFEST = Path("/usr/share/remote-dev/browser-archives.json")
BROWSERS = Path("/opt/remote-dev/playwright-browsers")
NOTICE = Path("/usr/share/doc/remote-dev/third_party/runtime/ffmpeg/LICENSE-from-binary.txt")
UID = 61123
GID = 61123
MAX_OUTPUT = 65536


class LicenseEvidenceError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise LicenseEvidenceError(reason)


def execute_ffmpeg(binary: Path, option: str) -> str:
    """Run without agent secrets or build-time network, as an unprivileged UID."""
    result = subprocess.run(
        [str(binary), option],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, timeout=20, cwd="/",
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
             "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        user=UID, group=GID, extra_groups=[],
    )
    return result.stdout


def generate(
    manifest: dict, browsers: Path, output: Path, arch: str,
    runner=execute_ffmpeg,
) -> None:
    require(arch in ("amd64", "arm64"), "unsupported FFmpeg architecture")
    try:
        amd64 = manifest["archives"]["amd64"]["ffmpeg"]
        arm64 = manifest["archives"]["arm64"]["ffmpeg"]
        selected = manifest["archives"][arch]["ffmpeg"]
    except (TypeError, KeyError) as exc:
        raise LicenseEvidenceError("missing reviewed FFmpeg archive") from exc
    revision = selected.get("revision")
    digest = selected.get("sha256")
    require(isinstance(revision, str) and revision.isdecimal(),
            "invalid FFmpeg archive revision")
    require(amd64.get("revision") == arm64.get("revision") == revision,
            "FFmpeg archive revisions differ across architectures")
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            "missing SHA-256 provenance")
    binary = browsers / ("ffmpeg-" + revision) / "ffmpeg-linux"
    require(binary.is_file() and not binary.is_symlink() and os.access(binary, os.X_OK),
            "verified FFmpeg executable missing")
    version = runner(binary, "-version")
    license_text = runner(binary, "-L")
    require(isinstance(version, str) and
            20 <= len(version) <= MAX_OUTPUT and "ffmpeg version" in version.lower(),
            "FFmpeg did not report a valid version/configuration")
    require(isinstance(license_text, str) and
            20 <= len(license_text) <= MAX_OUTPUT and
            any(marker in license_text.upper() for marker in ("GPL", "GNU")),
            "FFmpeg did not report its licensing terms")
    with binary.open("rb") as stream:
        binary_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = (
        "Playwright-provisioned FFmpeg: exact binary licensing evidence\n"
        f"Architecture: {arch}\n"
        f"Playwright archive revision: {revision}\n"
        f"Reviewed archive SHA-256: {digest}\n"
        f"Installed executable SHA-256: {binary_hash}\n"
        "Source: installed FFmpeg binary -version and -L output\n"
        "No substitute legal notice was supplied by the upstream ZIP.\n"
        "\n=== ffmpeg -version (build options) ===\n"
        + version.rstrip() + "\n"
        "\n=== ffmpeg -L (license) ===\n"
        + license_text.rstrip() + "\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    output.chmod(0o644)


def main() -> int:
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine)
    require(arch is not None, "unsupported FFmpeg build target")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    generate(manifest, BROWSERS, NOTICE, arch)
    print("Preserved exact FFmpeg binary license and build configuration", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LicenseEvidenceError, OSError, subprocess.SubprocessError) as exc:
        print("ERROR: FFmpeg license evidence unavailable: " + str(exc),
              file=sys.stderr)
        raise SystemExit(1) from None
