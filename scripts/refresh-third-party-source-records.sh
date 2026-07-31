#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"

command -v "$python_bin" >/dev/null 2>&1 \
  || { echo "ERROR: $python_bin is required to refresh legal source records" >&2; exit 1; }

"$python_bin" "$ROOT/scripts/legal-inventory.py" --root "$ROOT" refresh

# Keep the existing small SOURCE.env files as generated compatibility views for
# maintainers and older tooling. sources.lock.json remains the canonical source.
"$python_bin" - "$ROOT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

root = Path(sys.argv[1])
lock_path = root / "third_party/sources.lock.json"
lock_bytes = lock_path.read_bytes()
lock = json.loads(lock_bytes)
documents = lock.get("documents")
if not isinstance(documents, list) or not documents:
    raise SystemExit(f"ERROR: {lock_path} has no document records")
records = {
    record["path"]: record
    for record in documents
    if isinstance(record, dict) and isinstance(record.get("path"), str)
}


def lookup(source_path: str) -> dict[str, Any]:
    try:
        return records[source_path]
    except KeyError:
        raise SystemExit(
            f"ERROR: {lock_path} has no record for {source_path}; "
            "update the SOURCE.env compatibility mapping"
        ) from None


def write_view(output_path: str, lines: list[str]) -> None:
    destination = root / output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


codex_notice = lookup("third_party/components/codex/NOTICE")
codex_license = lookup("third_party/components/codex/LICENSE")
if codex_notice["version"] != codex_license["version"]:
    raise SystemExit("ERROR: Codex NOTICE and LICENSE records use different versions")
write_view(
    "third_party/components/codex/SOURCE.env",
    [
        "# Generated compatibility view for source-locked Codex legal documents.",
        f"CODEX_RELEASE_TAG={codex_notice['version']}",
        f"CODEX_NOTICE_URL={codex_notice['url']}",
        f"CODEX_NOTICE_GIT_BLOB_SHA1={codex_notice['git_blob_sha1']}",
        f"CODEX_LICENSE_URL={codex_license['url']}",
        f"CODEX_LICENSE_GIT_BLOB_SHA1={codex_license['git_blob_sha1']}",
    ],
)

mapping = {
    "third_party/components/github-cli/LICENSE": (
        "third_party/components/github-cli/SOURCE.env",
        "GH_VERSION",
        "GH_LICENSE_URL",
        "GH_LICENSE_GIT_BLOB_SHA1",
        "GitHub CLI license",
    ),
    "third_party/components/ttyd/LICENSE": (
        "third_party/components/ttyd/SOURCE.env",
        "TTYD_VERSION",
        "TTYD_LICENSE_URL",
        "TTYD_LICENSE_GIT_BLOB_SHA1",
        "ttyd license",
    ),
    "third_party/components/mise/LICENSE": (
        "third_party/components/mise/SOURCE.env",
        "MISE_VERSION",
        "MISE_LICENSE_URL",
        "MISE_LICENSE_GIT_BLOB_SHA1",
        "mise license",
    ),
    "third_party/components/python/LICENSE": (
        "third_party/components/python/SOURCE.env",
        "CPYTHON_VERSION",
        "CPYTHON_LICENSE_URL",
        "CPYTHON_LICENSE_GIT_BLOB_SHA1",
        "CPython license",
    ),
}

for source_path, (output_path, version_key, url_key, blob_key, label) in mapping.items():
    record = lookup(source_path)
    lines = [
        f"# Generated compatibility view for the source-locked {label}.",
        f"{version_key}={record['version']}",
        f"{url_key}={record['url']}",
        f"{blob_key}={record['git_blob_sha1']}",
    ]
    if source_path == "third_party/components/python/LICENSE":
        lines.append(f"LEGAL_SOURCE_SET_SHA256={hashlib.sha256(lock_bytes).hexdigest()}")
    write_view(output_path, lines)

uv_apache = lookup("third_party/components/uv/LICENSE-APACHE-2.0")
uv_mit = lookup("third_party/components/uv/LICENSE-MIT")
if uv_apache["version"] != uv_mit["version"]:
    raise SystemExit("ERROR: uv Apache-2.0 and MIT records use different versions")
write_view(
    "third_party/components/uv/SOURCE.env",
    [
        "# Generated compatibility view for the source-locked uv licenses.",
        f"UV_VERSION={uv_apache['version']}",
        f"UV_LICENSE_APACHE_URL={uv_apache['url']}",
        f"UV_LICENSE_APACHE_GIT_BLOB_SHA1={uv_apache['git_blob_sha1']}",
        f"UV_LICENSE_MIT_URL={uv_mit['url']}",
        f"UV_LICENSE_MIT_GIT_BLOB_SHA1={uv_mit['git_blob_sha1']}",
    ],
)
PY

printf 'Refreshed source-locked third-party legal documents and generated inventory.\n'
