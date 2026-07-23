#!/usr/bin/env bash
set -euo pipefail

image="${1:-codex-remote-dev:local}"
name="codex-remote-dev-smoke-${RANDOM}-$$"
guard_name="${name}-guard"
log_file="$(mktemp)"

cleanup() {
  docker rm -f "$name" "$guard_name" >/dev/null 2>&1 || true
  rm -f "$log_file"
}
trap cleanup EXIT

# Secure by default: startup without a password must fail unless explicitly overridden.
set +e
timeout 15 docker run --rm --name "$guard_name" "$image" >"$log_file" 2>&1
guard_status=$?
set -e

if (( guard_status == 0 )); then
  echo "ERROR: container started without web authentication" >&2
  exit 1
fi
if (( guard_status == 124 )); then
  echo "ERROR: unauthenticated startup did not fail within 15 seconds" >&2
  exit 1
fi
if ! grep -Fq "web authentication is not configured" "$log_file"; then
  echo "ERROR: unauthenticated startup failed for an unexpected reason" >&2
  cat "$log_file" >&2
  exit 1
fi

echo "Secure startup guard: OK"

docker run -d \
  --name "$name" \
  --env ALLOW_INSECURE_WEB=1 \
  --env WEB_CHECK_ORIGIN=0 \
  --env START_MODE=shell \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$name" curl -fsS http://127.0.0.1:7681/ >/dev/null 2>&1; then
    docker exec "$name" pgrep -x ttyd >/dev/null
    echo "Web entrypoint smoke test: OK"
    exit 0
  fi

  if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" != "true" ]]; then
    echo "ERROR: runtime smoke container stopped unexpectedly" >&2
    docker logs "$name" >&2 || true
    exit 1
  fi

  sleep 1
done

echo "ERROR: ttyd did not become ready within 30 seconds" >&2
docker logs "$name" >&2 || true
exit 1
