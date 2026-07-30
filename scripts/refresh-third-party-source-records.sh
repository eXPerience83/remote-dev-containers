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

root = Path(sys.argv[1])
lock_path = root / "third_party/sources.lock.json"
lock_bytes = lock_path.read_bytes()
lock = json.loads(lock_bytes)
records = {record["path"]: record for record in lock["documents"]}

mapping = {
    "third_party/components/codex/NOTICE": (
        "third_party/components/codex/SOURCE.env",
        "CODEX_RELEASE_TAG",
        "CODEX_NOTICE_URL",
        "CODEX_NOTICE_GIT_BLOB_SHA1",
        "Codex NOTICE",
    ),
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
    record = records[source_path]
    lines = [
        f"# Generated compatibility view for the source-locked {label}.",
        f"{version_key}={record['version']}",
        f"{url_key}={record['url']}",
        f"{blob_key}={record['git_blob_sha1']}",
    ]
    if source_path == "third_party/components/python/LICENSE":
        lines.append(f"LEGAL_SOURCE_SET_SHA256={hashlib.sha256(lock_bytes).hexdigest()}")
    destination = root / output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")

uv_records = [
    records["third_party/components/uv/LICENSE-APACHE-2.0"],
    records["third_party/components/uv/LICENSE-MIT"],
]
uv_lines = [
    "# Generated compatibility view for the source-locked uv licenses.",
    f"UV_VERSION={uv_records[0]['version']}",
    f"UV_LICENSE_APACHE_URL={uv_records[0]['url']}",
    f"UV_LICENSE_APACHE_GIT_BLOB_SHA1={uv_records[0]['git_blob_sha1']}",
    f"UV_LICENSE_MIT_URL={uv_records[1]['url']}",
    f"UV_LICENSE_MIT_GIT_BLOB_SHA1={uv_records[1]['git_blob_sha1']}",
]
uv_destination = root / "third_party/components/uv/SOURCE.env"
uv_destination.write_text("\n".join(uv_lines) + "\n", encoding="utf-8")
PY

# check-upstream.yml historically stages an explicit allowlist. During that
# workflow, pre-stage newly generated machine files that are outside the old
# list; source records already on the list stay unstaged for its change test.
if [[ "${GITHUB_ACTIONS:-}" == "true" ]] \
  && [[ "$(git -C "$ROOT" branch --show-current)" == "automation/update-upstreams" ]]; then
  git -C "$ROOT" add -- \
    third_party/inventory.json \
    third_party/sources.lock.json \
    third_party/README.md \
    third_party/components/uv/LICENSE-APACHE-2.0 \
    third_party/components/uv/LICENSE-MIT \
    third_party/components/uv/SOURCE.env
fi

printf 'Refreshed source-locked third-party legal documents and generated inventory.\n'
