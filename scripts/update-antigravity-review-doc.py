#!/usr/bin/env python3
"""Refresh the machine-owned current Antigravity review summary in Markdown."""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RECONCILE_PATH = ROOT / "reconcile-antigravity-review-state.py"
SPEC = importlib.util.spec_from_file_location("antigravity_reconcile", RECONCILE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load reconcile-antigravity-review-state.py")
RECONCILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILE)

START = "<!-- remote-dev-antigravity-current-review:start -->"
END = "<!-- remote-dev-antigravity-current-review:end -->"
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_ALLOWED_STRATEGIES = {"custom-directory", "skip-shell-modification-flags"}


class DocumentError(ValueError):
    """Raised when evidence cannot be rendered into the bounded Markdown block."""


def render(reviewed: dict[str, Any]) -> str:
    RECONCILE.validate_reviewed(reviewed, baseline=reviewed)
    date = reviewed.get("inspection_date_utc")
    installer = reviewed.get("installer")
    binary = reviewed.get("installed_binary")
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise DocumentError("review evidence has an invalid inspection date")
    if not isinstance(installer, dict) or not isinstance(binary, dict):
        raise DocumentError("review evidence has malformed installer/binary metadata")

    installer_size = installer.get("size")
    binary_size = binary.get("size")
    if not isinstance(installer_size, int) or not 0 < installer_size <= 2 * 1024 * 1024:
        raise DocumentError("review evidence has an invalid installer size")
    if not isinstance(binary_size, int) or not 0 < binary_size <= RECONCILE.MAX_PAYLOAD_BYTES:
        raise DocumentError("review evidence has an invalid payload size")
    installer_sha = RECONCILE.sha256(installer.get("sha256"), "installer SHA-256")
    binary_sha = RECONCILE.sha256(binary.get("sha256"), "payload SHA-256")
    version = binary.get("version")
    if not isinstance(version, str) or not RECONCILE._VERSION_RE.fullmatch(version):
        raise DocumentError("review evidence has an invalid payload version")
    strategy = installer.get("selected_strategy")
    if strategy not in _ALLOWED_STRATEGIES:
        raise DocumentError("review evidence has an unsupported installer strategy")
    hosts = installer.get("referenced_https_hosts")
    if not isinstance(hosts, list) or hosts != sorted(set(hosts)):
        raise DocumentError("review evidence has non-normalized installer host metadata")
    if any(not isinstance(host, str) or not _HOST_RE.fullmatch(host) for host in hosts):
        raise DocumentError("review evidence has unsafe installer host metadata")
    hosts_text = ", ".join(f"`{host}`" for host in hosts) if hosts else "none recorded"

    return "\n".join(
        [
            START,
            "",
            "Current committed normalized review evidence:",
            "",
            f"- inspection date: **{date} UTC**;",
            f"- official installer: `{RECONCILE.OFFICIAL_URL}`;",
            f"- installer SHA-256: `{installer_sha}` ({installer_size:,} bytes);",
            f"- selected installer strategy: `{strategy}`;",
            f"- referenced HTTPS hosts: {hosts_text};",
            f"- installed payload: `agy` **{version}**, SHA-256 `{binary_sha}` ({binary_size:,} bytes);",
            "- blocking findings: **none**.",
            "",
            "This summary is generated only from schema-validated metadata. It never embeds vendor stdout/stderr or proprietary bytes.",
            "",
            END,
        ]
    )


def update_document(text: str, reviewed: dict[str, Any]) -> str:
    if text.count(START) != 1 or text.count(END) != 1:
        raise DocumentError("Antigravity review document must contain exactly one managed summary block")
    start = text.index(START)
    end = text.index(END, start) + len(END)
    if end <= start:
        raise DocumentError("Antigravity review summary markers are malformed")
    return text[:start] + render(reviewed) + text[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviewed", type=Path, required=True)
    parser.add_argument(
        "--document", type=Path, default=Path("third_party/antigravity-cli-inspection.md")
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        reviewed = RECONCILE.load_json(args.reviewed)
        original = args.document.read_text(encoding="utf-8")
        updated = update_document(original, reviewed)
        if args.write:
            args.document.write_text(updated, encoding="utf-8")
        elif updated != original:
            raise DocumentError("Antigravity review Markdown summary is stale")
    except (OSError, RECONCILE.ReconcileError, DocumentError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 1
    print("Antigravity review Markdown summary: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
