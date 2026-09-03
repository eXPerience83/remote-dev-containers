#!/usr/bin/env python3
"""Run full Antigravity inspection only after a strict pre-download/hash gate.

The official installer is fetched through the shared reviewed HTTPS policy,
verified against the explicitly admitted SHA-256, and only then handed to the
existing inspector as a local fixture. This prevents urllib from following an
unreviewed redirect before installer admission is checked.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from pathlib import Path

import antigravity_download as NETWORK

ROOT = Path(__file__).resolve().parent
INSPECTOR_PATH = ROOT / "inspect-antigravity-cli.py"
SPEC = importlib.util.spec_from_file_location("antigravity_inspector", INSPECTOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load inspect-antigravity-cli.py")
INSPECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSPECTOR)

MAX_INSTALLER_BYTES = 2 * 1024 * 1024


class InspectionGateError(RuntimeError):
    """Raised before vendor execution when the pre-inspection gate fails."""


def installer_url_policy(url: str) -> bool:
    """Allow only the exact canonical installer URL, including redirects."""
    return url == INSPECTOR.OFFICIAL_INSTALLER_URL


def inspect_prefetched_installer(
    *,
    installer: Path,
    expected_installer_sha256: str,
    expected_payload_sha256: str,
    content_type: str | None,
) -> dict:
    """Inspect a local installer only after its caller verified the exact hash."""
    actual = INSPECTOR.sha256_file(installer)
    if actual != expected_installer_sha256:
        raise InspectionGateError(
            "prefetched installer SHA-256 differs from the explicitly admitted value"
        )

    report = INSPECTOR.inspect(
        installer,
        expected_installer_sha256,
        expected_payload_sha256,
    )
    # The inspector intentionally labels local fixture inputs as fixture:*.
    # Restore the already-validated network provenance before artifact validation.
    report["installer"]["source"] = INSPECTOR.OFFICIAL_INSTALLER_URL
    report["installer"]["final_url"] = INSPECTOR.OFFICIAL_INSTALLER_URL
    report["installer"]["content_type"] = content_type
    report["blocking_findings"] = INSPECTOR.validate_report(report)
    return report


def run_inspection(
    *,
    expected_installer_sha256: str,
    expected_payload_sha256: str,
) -> dict:
    """Fetch/hash the installer safely, then perform the admitted full inspection."""
    with tempfile.TemporaryDirectory(prefix="antigravity-prefetch-") as temporary:
        installer = Path(temporary) / "install.sh"
        try:
            data, content_type, final_url = NETWORK.download_bytes(
                INSPECTOR.OFFICIAL_INSTALLER_URL,
                installer,
                max_bytes=MAX_INSTALLER_BYTES,
                policy=installer_url_policy,
                user_agent="remote-dev-containers-antigravity-inspection",
            )
        except NETWORK.DownloadError as exc:
            raise InspectionGateError(str(exc)) from exc

        if final_url != INSPECTOR.OFFICIAL_INSTALLER_URL:
            raise InspectionGateError("official installer redirected unexpectedly")
        if INSPECTOR.sha256_bytes(data) != expected_installer_sha256:
            raise InspectionGateError(
                "downloaded installer SHA-256 differs from the explicitly admitted value"
            )
        return inspect_prefetched_installer(
            installer=installer,
            expected_installer_sha256=expected_installer_sha256,
            expected_payload_sha256=expected_payload_sha256,
            content_type=content_type,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-installer-sha256", type=INSPECTOR.parse_sha256, required=True
    )
    parser.add_argument(
        "--expected-binary-sha256", type=INSPECTOR.parse_sha256, required=True
    )
    args = parser.parse_args()
    try:
        report = run_inspection(
            expected_installer_sha256=args.expected_installer_sha256,
            expected_payload_sha256=args.expected_binary_sha256,
        )
    except (OSError, RuntimeError, InspectionGateError) as exc:
        print(f"Antigravity inspection rejected before/at admitted execution: {exc}", file=__import__("sys").stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    findings = report.get("blocking_findings")
    if findings:
        print(f"Antigravity inspection found {len(findings)} blocking issue(s).", file=__import__("sys").stderr)
        return 1
    print("Antigravity inspection: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
