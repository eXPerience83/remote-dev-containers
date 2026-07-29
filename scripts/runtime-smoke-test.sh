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
    for expected_line in \
      'Inner sandbox: disabled explicitly' \
      'Isolation boundary: outer container' \
      'Codex approval policy: untrusted'; do
      if ! grep -Fxq "$expected_line" <<<"$policy_output"; then
        echo "ERROR: Codex launch policy is missing: $expected_line" >&2
        printf '%s\n' "$policy_output" >&2
        exit 1
      fi
    done

    doctor_output="$(docker exec "$name" codex-doctor)"
    for expected_line in \
      'Inner sandbox: disabled explicitly' \
      'Isolation boundary: outer container' \
      'Codex approval policy: untrusted'; do
      if ! grep -Fxq "$expected_line" <<<"$doctor_output"; then
        echo "ERROR: diagnostics are missing: $expected_line" >&2
        printf '%s\n' "$doctor_output" >&2
        exit 1
      fi
    done

    echo "Pinned Codex launcher and resume compatibility: OK"
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
