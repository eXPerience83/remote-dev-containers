#!/usr/bin/env bash
set -euo pipefail

image="${1:-remote-dev:local}"
name="remote-dev-web-password-${RANDOM}-$$"
malformed_name="${name}-malformed"
log_file="$(mktemp)"
secret="synthetic-agent-password-${RANDOM}-$$"

cleanup() {
  docker rm -f "$name" "$malformed_name" >/dev/null 2>&1 || true
  rm -f "$log_file"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# The configured value must be consumed by the startup wrapper rather than
# inherited by ttyd or terminal child processes as a generic environment value.
docker run -d \
  --name "$name" \
  --env "WEB_PASSWORD=$secret" \
  --env WEB_CHECK_ORIGIN=1 \
  --env START_MODE=shell \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$name" pgrep -x ttyd >/dev/null 2>&1; then
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" != true ]]; then
    docker logs "$name" >&2 || true
    fail "authenticated agent stopped before ttyd became ready"
  fi
  sleep 1
done

docker exec "$name" pgrep -x ttyd >/dev/null 2>&1 \
  || fail "authenticated agent did not start ttyd"

if docker exec "$name" sh -c '
  pid="$(pgrep -xo ttyd)"
  tr "\0" "\n" < "/proc/$pid/environ" | grep -q "^WEB_PASSWORD="
'; then
  fail "WEB_PASSWORD remained in the ttyd child-process environment"
fi

status="$(docker exec "$name" curl --silent --output /dev/null --write-out '%{http_code}' \
  --user "codex:$secret" http://127.0.0.1:7681/)" \
  || fail "authenticated ttyd request could not be evaluated"
[[ "$status" == 200 ]] || fail "authenticated ttyd request returned $status"

docker rm -f "$name" >/dev/null

# CR/LF values must fail before ttyd starts, and error output must not echo any
# reusable password material.
for delimiter in newline carriage-return; do
  : >"$log_file"
  if [[ "$delimiter" == newline ]]; then
    malformed_password=$'synthetic-agent-first\nsynthetic-agent-second'
  else
    malformed_password=$'synthetic-agent-first\rsynthetic-agent-second'
  fi

  malformed_status=0
  timeout 15 docker run --rm \
    --name "$malformed_name" \
    --env "WEB_PASSWORD=$malformed_password" \
    "$image" >"$log_file" 2>&1 || malformed_status=$?

  [[ "$malformed_status" != 0 ]] \
    || fail "$delimiter password unexpectedly started an agent terminal"
  [[ "$malformed_status" != 124 ]] \
    || fail "$delimiter password did not fail closed within 15 seconds"
  grep -Fq 'web password must be a single line' "$log_file" \
    || fail "$delimiter password failed for an unexpected reason"
  if grep -Fq 'synthetic-agent-first' "$log_file"; then
    fail "$delimiter password material was echoed to logs"
  fi
done

echo "Agent WEB_PASSWORD consumption and malformed-value rejection: OK"
