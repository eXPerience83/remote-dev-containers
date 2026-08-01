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
trap 'exit 130' INT
trap 'exit 143' TERM

assert_output_lines() {
  local label="$1"
  local output="$2"
  shift 2

  for expected_line in "$@"; do
    if ! grep -Fxq "$expected_line" <<<"$output"; then
      echo "ERROR: $label is missing: $expected_line" >&2
      printf '%s\n' "$output" >&2
      exit 1
    fi
  done
}

# Secure by default: startup without a password must fail unless explicitly overridden.
guard_status=0
if timeout 15 docker run --rm --name "$guard_name" "$image" >"$log_file" 2>&1; then
  guard_status=0
else
  guard_status=$?
fi

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
  --security-opt no-new-privileges:true \
  --env ALLOW_INSECURE_WEB=1 \
  --env WEB_CHECK_ORIGIN=0 \
  --env START_MODE=shell \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$name" curl -fsS http://127.0.0.1:7681/ >/dev/null 2>&1; then
    docker exec "$name" pgrep -x ttyd >/dev/null

    if docker exec "$name" sh -c 'command -v bwrap >/dev/null 2>&1'; then
      echo "ERROR: the system Bubblewrap executable is present in the default outer-isolation image" >&2
      exit 1
    fi

    codex_version="$(docker exec "$name" codex --version)"
    launcher_version="$(docker exec "$name" run-codex --version)"
    if [[ "$launcher_version" != "$codex_version" ]]; then
      echo "ERROR: run-codex did not execute the pinned Codex binary with its fixed policy" >&2
      printf 'Raw Codex: %s\nLauncher: %s\n' "$codex_version" "$launcher_version" >&2
      exit 1
    fi
    docker exec "$name" run-codex resume --help >/dev/null

    policy_output="$(docker exec "$name" run-codex --print-policy)"
    assert_output_lines 'default Codex launch policy' "$policy_output" \
      'Inner sandbox: disabled explicitly' \
      'Isolation boundary: outer container' \
      'Codex approval mode: autonomous' \
      'Codex approval policy: never' \
      'Mode source: default'

    guarded_output="$(docker exec \
      --env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded \
      "$name" run-codex --print-policy)"
    assert_output_lines 'guarded deployment policy' "$guarded_output" \
      'Codex approval mode: guarded' \
      'Codex approval policy: untrusted' \
      'Mode source: deployment'

    override_output="$(docker exec \
      --env REMOTE_DEV_CODEX_APPROVAL_MODE=guarded \
      "$name" run-codex --approval-mode autonomous --print-policy)"
    assert_output_lines 'per-launch policy override' "$override_output" \
      'Codex approval mode: autonomous' \
      'Codex approval policy: never' \
      'Mode source: per-launch'

    doctor_output="$(docker exec "$name" codex-doctor)"
    assert_output_lines 'Codex diagnostics' "$doctor_output" \
      'Inner sandbox: disabled explicitly' \
      'Isolation boundary: outer container' \
      'Codex approval mode: autonomous' \
      'Codex approval policy: never' \
      'Mode source: default'

    echo "Pinned Codex launcher and resume compatibility: OK"
    echo "Configurable Codex approval modes: OK"
    echo "Explicit outer-isolation policy: OK"
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
