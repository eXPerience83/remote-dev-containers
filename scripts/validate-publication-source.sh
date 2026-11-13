#!/usr/bin/env bash
# Shared source preflight for the stable, edge and reviewed candidate publishers.
# Keep channel-specific release/digest/authorization gates in their workflows.
set -euo pipefail

if (( $# != 1 )); then
  echo "Usage: bash scripts/validate-publication-source.sh stable|edge|candidate" >&2
  exit 2
fi

case "$1" in
  stable) validate_compose=0 ;;
  edge|candidate) validate_compose=1 ;;
  *)
    echo "ERROR: unsupported publication source validation mode: $1" >&2
    exit 2
    ;;
esac

test -d scripts
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find scripts -type f -name '*.sh' -print0)

REMOTE_DEV_IMAGE_NAMES_LIB=./scripts/lib/remote-dev-image-names.sh \
  bash scripts/test-image-name-compat.sh
bash scripts/test-image-identity.sh
python3 scripts/test_edge_build_identity.py
python3 scripts/test_update_upstream_changelog.py
bash scripts/validate-version-pins.sh
bash scripts/test-source-revision.sh
jq -e . renovate.json >/dev/null
python3 scripts/validate-renovate-ownership.py --root .

if (( validate_compose == 1 )); then
  for file in compose/*.yml; do
    docker compose -f "$file" config --quiet
    echo "OK $file"
  done
fi

# Edge must rebuild when any locally copied Dockerfile input changes.
if [[ "$1" == edge ]]; then
  python3 scripts/test_edge_publication_paths.py
fi
