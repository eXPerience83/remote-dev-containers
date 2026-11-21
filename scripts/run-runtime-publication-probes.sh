#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 && $# != 4 )); then
  echo "Usage: $0 IMAGE [VERSION REVISION CHANNEL]" >&2
  exit 2
fi
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
runtime_ref="$1"
shift

docker run --rm --entrypoint /usr/local/bin/codex-smoke-test \
  "$runtime_ref" "$@"
docker run --rm \
  --network none \
  --entrypoint /opt/remote-dev/mise/shims/python \
  -v "$root/scripts/test-remote-dev-context7-runtime-isolation.py:/tmp/test-remote-dev-context7-runtime-isolation.py:ro" \
  -e REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER=/usr/local/bin/remote-dev-context7-device-login \
  "$runtime_ref" /tmp/test-remote-dev-context7-runtime-isolation.py

timeout --foreground 60s docker run --rm \
  --user 0:0 \
  --network none \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --entrypoint /opt/remote-dev/mise/shims/python \
  -v "$root/scripts/test-codex-runtime-noexec-staging.py:/tmp/test-codex-runtime-noexec-staging.py:ro" \
  -e REMOTE_DEV_CODEX_RUNTIME_MANAGER=/usr/local/bin/remote-dev-codex-runtime \
  "$runtime_ref" /tmp/test-codex-runtime-noexec-staging.py

bash "$root/scripts/runtime-smoke-test.sh" "$runtime_ref"
bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"
bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"
