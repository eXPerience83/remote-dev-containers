#!/usr/bin/env bash
set -euo pipefail

image="${1:-remote-dev:local}"
name="remote-dev-smoke-${RANDOM}-$$"
launcher_name="${name}-launcher"
guard_name="${name}-guard"
log_file="$(mktemp)"
launcher_secret='synthetic-launcher-secret'

cleanup() {
  docker rm -f "$name" "$launcher_name" "$guard_name" >/dev/null 2>&1 || true
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

assert_antigravity_entrypoint_blocked() {
  local label="$1"
  shift
  local output=""
  local command_status=0

  output="$(docker exec \
    --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=0 \
    "$name" "$@" 2>&1)" || command_status=$?
  if (( command_status != 2 )); then
    echo "ERROR: $label returned $command_status outside the Antigravity service, expected 2" >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi
  if ! grep -Eq 'experimental and blocked pending TrueNAS validation|gated REMOTE_DEV_ROLE=antigravity' <<<"$output"; then
    echo "ERROR: $label did not explain the gated Antigravity service requirement" >&2
    printf '%s\n' "$output" >&2
    exit 1
  fi
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
    docker exec "$name" remote-dev-healthcheck

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
      'Project trust: untrusted (launch-scoped)' \
      'Approval behavior: prompt for commands except explicit exec-policy allows' \
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

    assert_antigravity_entrypoint_blocked \
      'Antigravity role diagnostics' \
      env REMOTE_DEV_ROLE=antigravity remote-dev-doctor
    assert_antigravity_entrypoint_blocked \
      'Antigravity runtime manager' \
      remote-dev-antigravity status --menu
    assert_antigravity_entrypoint_blocked \
      'Antigravity installer wrapper' \
      remote-dev-install-antigravity --yes
    assert_antigravity_entrypoint_blocked \
      'Antigravity updater wrapper' \
      remote-dev-update-antigravity --yes
    assert_antigravity_entrypoint_blocked \
      'Antigravity launcher' \
      run-antigravity
    antigravity_binary="$(
      docker exec "$name" bash -c \
        '. /usr/local/lib/remote-dev/antigravity-paths.sh; printf "%s" "$ANTIGRAVITY_BINARY"'
    )"
    if docker exec "$name" test -e "$antigravity_binary"; then
      echo "ERROR: a blocked Antigravity entry point created the vendor executable in the Codex service" >&2
      exit 1
    fi

    docker exec "$name" sh -c '
      install -d -m 0755 /tmp/remote-dev-doctor-fixture
      printf "%s\n" \
        "#!/usr/bin/env bash" \
        "case \"\${1:-}\" in" \
        "  verify)" \
        "    if [[ \"\${REMOTE_DEV_TEST_ANTIGRAVITY_VERIFY_FAIL:-0}\" = 1 ]]; then" \
        "      echo \"Antigravity runtime full integrity: FAILED (synthetic)\" >&2" \
        "      exit 3" \
        "    fi" \
        "    echo \"Antigravity runtime full integrity: OK (1.1.8)\"" \
        "    ;;" \
        "  status)" \
        "    echo \"Antigravity: 1.1.8 (update to reviewed 1.1.9 required)\"" \
        "    exit 3" \
        "    ;;" \
        "  *) exit 2 ;;" \
        "esac" \
        > /tmp/remote-dev-doctor-fixture/remote-dev-antigravity
      printf "%s\n" \
        "#!/usr/bin/env bash" \
        "if [[ \"\${REMOTE_DEV_TEST_ANTIGRAVITY_VERIFY_TIMEOUT:-0}\" = 1 ]]; then exit 124; fi" \
        "[[ \"\${1:-}\" = --signal=TERM ]] && shift" \
        "[[ \"\${1:-}\" = --kill-after=5s ]] && shift" \
        "[[ \"\${1:-}\" = 60s ]] && shift" \
        "exec \"\$@\"" \
        > /tmp/remote-dev-doctor-fixture/timeout
      chmod 0755 /tmp/remote-dev-doctor-fixture/remote-dev-antigravity
      chmod 0755 /tmp/remote-dev-doctor-fixture/timeout
    '
    antigravity_doctor_output="$(
      docker exec \
        --env REMOTE_DEV_ROLE=antigravity \
        --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
        "$name" sh -c 'PATH=/tmp/remote-dev-doctor-fixture:$PATH exec remote-dev-doctor'
    )"
    assert_output_lines 'experimental Antigravity diagnostics' "$antigravity_doctor_output" \
      'Role: antigravity' \
      'Antigravity runtime full integrity: OK (1.1.8)' \
      'Antigravity: 1.1.8 (update to reviewed 1.1.9 required)' \
      'Antigravity support status: experimental validation only; not yet a supported integration.'

    antigravity_doctor_failure="$(
      docker exec \
        --env REMOTE_DEV_ROLE=antigravity \
        --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
        --env REMOTE_DEV_TEST_ANTIGRAVITY_VERIFY_FAIL=1 \
        "$name" sh -c 'PATH=/tmp/remote-dev-doctor-fixture:$PATH remote-dev-doctor' 2>&1
    )" && fail "Antigravity diagnostics accepted failed full integrity"
    assert_output_lines 'failed Antigravity integrity diagnostics' "$antigravity_doctor_failure" \
      'Antigravity runtime full integrity: unavailable (exit 3)'

    antigravity_doctor_timeout="$(
      docker exec \
        --env REMOTE_DEV_ROLE=antigravity \
        --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
        --env REMOTE_DEV_TEST_ANTIGRAVITY_VERIFY_TIMEOUT=1 \
        "$name" sh -c 'PATH=/tmp/remote-dev-doctor-fixture:$PATH remote-dev-doctor' 2>&1
    )" && fail "Antigravity diagnostics accepted a full-integrity timeout"
    assert_output_lines 'timed-out Antigravity integrity diagnostics' "$antigravity_doctor_timeout" \
      'Antigravity runtime full integrity: unavailable (exit 124)'

    docker run -d \
      --name "$launcher_name" \
      --security-opt no-new-privileges:true \
      --env REMOTE_DEV_ROLE=launcher \
      --env REMOTE_DEV_START_MODE=menu \
      --env WEB_BIND=0.0.0.0 \
      --env WEB_PORT=7680 \
      --env WEB_BASE_PATH=/launcher// \
      --env WEB_USERNAME=remote-dev \
      --env WEB_PASSWORD="$launcher_secret" \
      --env WEB_CHECK_ORIGIN=1 \
      --env REMOTE_DEV_LAUNCHER_CODEX_PORT=7681 \
      --env REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED=1 \
      --env REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PORT=7682 \
      "$image" >/dev/null

    for _ in $(seq 1 30); do
      if docker exec "$launcher_name" \
        curl -fsS http://127.0.0.1:7680/launcher/healthz >/dev/null 2>&1; then
        break
      fi
      if [[ "$(docker inspect -f '{{.State.Running}}' "$launcher_name" 2>/dev/null || true)" != true ]]; then
        echo "ERROR: launcher smoke container stopped unexpectedly" >&2
        docker logs "$launcher_name" >&2 || true
        exit 1
      fi
      sleep 1
    done

    docker exec "$launcher_name" remote-dev-healthcheck
    unauthenticated_status="$(docker exec "$launcher_name" \
      curl --silent --output /dev/null --write-out '%{http_code}' \
      http://127.0.0.1:7680/launcher/)"
    if [[ "$unauthenticated_status" != 401 ]]; then
      echo "ERROR: launcher returned $unauthenticated_status without authentication" >&2
      exit 1
    fi
    launcher_page="$(docker exec "$launcher_name" \
      curl --fail --silent --show-error \
      --user "remote-dev:${launcher_secret}" \
      --header 'Origin: http://127.0.0.1:7680' \
      http://127.0.0.1:7680/launcher/)"
    grep -Fq 'Open Codex' <<<"$launcher_page"
    grep -Fq '"port":7681' <<<"$launcher_page"
    grep -Fq 'Open Antigravity (experimental)' <<<"$launcher_page"
    grep -Fq '"port":7682' <<<"$launcher_page"
    if grep -Fq "$launcher_secret" <<<"$launcher_page"; then
      echo "ERROR: launcher page exposed its web password" >&2
      exit 1
    fi

    launcher_doctor="$(docker exec "$launcher_name" remote-dev-doctor)"
    assert_output_lines 'Launcher diagnostics' "$launcher_doctor" \
      'Role: launcher' \
      'Available roles: launcher, codex, shell' \
      'Experimental gated role: antigravity (requires REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1)' \
      'Launcher state boundary: no agent workspace or credential mounts are required.'

    codex_image_id="$(docker inspect -f '{{.Image}}' "$name")"
    launcher_image_id="$(docker inspect -f '{{.Image}}' "$launcher_name")"
    if [[ "$codex_image_id" != "$launcher_image_id" ]]; then
      echo "ERROR: launcher and Codex containers do not reuse one image ID" >&2
      exit 1
    fi
    if [[ "$(docker inspect -f '{{json .Mounts}}' "$launcher_name")" != '[]' ]]; then
      echo "ERROR: isolated launcher smoke container unexpectedly has mounts" >&2
      docker inspect -f '{{json .Mounts}}' "$launcher_name" >&2
      exit 1
    fi

    echo "Pinned Codex launcher and resume compatibility: OK"
    echo "Configurable Codex approval modes: OK"
    echo "Explicit outer-isolation policy: OK"
    echo "Experimental Antigravity gate, entry-point isolation and optional doctor status: OK"
    echo "Authenticated isolated launcher role: OK"
    echo "Launcher base-path normalization: OK"
    echo "Launcher and Codex same-image reuse: OK"
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
