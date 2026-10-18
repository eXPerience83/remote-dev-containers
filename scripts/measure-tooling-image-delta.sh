#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
# Compare the PR merge-base using the same runner, build inputs and APT window.
baseline_revision="${BASELINE_REVISION:-$(git merge-base origin/main HEAD)}"
if [[ "$baseline_revision" == "$(git rev-parse HEAD)" ]]; then
  baseline_revision="$(git rev-parse HEAD^)"
fi
scratch="$(mktemp -d)"
trap 'rm -rf -- "$scratch"' EXIT
mkdir "$scratch/source"
git archive "$baseline_revision" | tar -x -C "$scratch/source"
docker build --platform linux/amd64 -t remote-dev-base:pr2-before \
  -f "$scratch/source/images/base/Dockerfile" "$scratch/source"
docker build --platform linux/amd64 -t remote-dev:pr2-before \
  --build-arg BASE_IMAGE=remote-dev-base:pr2-before \
  --build-arg "SOURCE_REVISION=$baseline_revision" \
  -f "$scratch/source/images/codex/Dockerfile" "$scratch/source"
python3 - "$baseline_revision" <<'PY'
import json
import subprocess
import sys

def size(image):
    return int(subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Size}}'], text=True))

report = {'before_revision': sys.argv[1], 'candidate_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'images': {}}
for image in ('remote-dev-base', 'remote-dev'):
    before, after = size(image + ':pr2-before'), size(image + ':local')
    report['images'][image] = {'before_bytes': before, 'after_bytes': after, 'delta_bytes': after - before, 'delta_mib': round((after - before) / 2**20, 2)}
report['requires_size_review'] = any(r['delta_bytes'] > 50 * 2**20 for r in report['images'].values())
report['compressed_size'] = 'Not measured: local Docker image sizes are uncompressed; no registry publication performed.'
print(json.dumps(report, indent=2))
with open('tooling-image-delta.json', 'w') as handle:
    json.dump(report, handle, indent=2)
PY
