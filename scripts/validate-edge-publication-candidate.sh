#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "Usage: $0 <base@digest> <runtime@digest> <source-sha> <edge-version>" >&2
  exit 2
fi

base_ref="$1"
runtime_ref="$2"
expected_revision="$3"
expected_version="$4"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

fail() {
  echo "ERROR: edge publication candidate validation: $*" >&2
  exit 1
}

[[ "$base_ref" =~ ^ghcr\.io/experience83/remote-dev-base@sha256:[0-9a-f]{64}$ ]] \
  || fail "base reference is not the canonical immutable AMD64 repository digest"
[[ "$runtime_ref" =~ ^ghcr\.io/experience83/remote-dev@sha256:[0-9a-f]{64}$ ]] \
  || fail "runtime reference is not the canonical immutable AMD64 repository digest"
[[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] \
  || fail "expected source revision must be a full lowercase Git SHA"
[[ "$expected_version" =~ ^edge-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9a-f]{7}$ ]] \
  || fail "expected edge version is malformed"
[[ "${expected_version##*-}" == "${expected_revision:0:7}" ]] \
  || fail "edge version short SHA does not match expected source revision"

for ref in "$base_ref" "$runtime_ref"; do
  docker pull --quiet "$ref" >/dev/null
done

runtime_image_id="$(docker image inspect "$runtime_ref" --format '{{.Id}}')" \
  || fail "could not resolve the pulled runtime image ID"
[[ "$runtime_image_id" =~ ^sha256:[0-9a-f]{64}$ ]] \
  || fail "pulled runtime image ID is malformed"

assert_label() {
  local ref="$1"
  local key="$2"
  local expected="$3"
  local actual
  actual="$(docker image inspect "$ref" --format "{{ index .Config.Labels \"$key\" }}")" \
    || fail "could not inspect $key on $ref"
  [[ "$actual" == "$expected" ]] \
    || fail "$ref label $key is '$actual', expected '$expected'"
}

for ref in "$base_ref" "$runtime_ref"; do
  platform="$(docker image inspect "$ref" --format '{{.Os}}/{{.Architecture}}')" \
    || fail "could not inspect platform on $ref"
  [[ "$platform" == linux/amd64 ]] \
    || fail "$ref platform is '$platform', expected 'linux/amd64'"
  assert_label "$ref" org.opencontainers.image.revision "$expected_revision"
  assert_label "$ref" org.opencontainers.image.version "$expected_version"
  assert_label "$ref" io.github.experience83.remote-dev.channel edge
done

candidate_startup_metadata() {
  echo "Exact candidate startup config (safe fields only):" >&2
  docker image inspect --format \
    'entrypoint={{json .Config.Entrypoint}} cmd={{json .Config.Cmd}} user={{json .Config.User}} workdir={{json .Config.WorkingDir}}' \
    "$runtime_image_id" >&2 \
    || fail "could not inspect safe runtime startup config"

  echo "Exact candidate startup path metadata:" >&2
  docker run --rm \
    --network none \
    --read-only \
    --user 0:0 \
    --entrypoint /usr/bin/stat \
    "$runtime_image_id" \
    -Lc '%n uid=%u gid=%g mode=%a size=%s' \
    /usr/bin/tini \
    /usr/local/bin/start-remote-dev-web \
    /usr/local/lib/remote-dev/remote-dev-runtime.sh \
    /usr/local/bin/remote-dev-launcher \
    /usr/bin/env \
    /bin/bash >&2 \
    || fail "could not inspect exact candidate startup path metadata"
}

strict_launcher_preflight() (
  set -euo pipefail
  local suffix="${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-0}-${RANDOM}"
  local network="remote-dev-edge-launcher-${suffix}"
  local container="remote-dev-edge-launcher-${suffix}"

  cleanup() {
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker rm -f "${container}-env-python3" >/dev/null 2>&1 || true
    docker rm -f "${container}-python-launcher" >/dev/null 2>&1 || true
    docker rm -f "${container}-start-script" >/dev/null 2>&1 || true
    docker rm -f "${container}-direct" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
  }

  strict_run_args=(
    --network "$network"
    --ipc private
    --read-only
    --user 65532:65532
    --cap-drop ALL
    --pids-limit 64
    --security-opt no-new-privileges:true
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777
    --tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755
    --env REMOTE_DEV_ROLE=launcher
    --env REMOTE_DEV_START_MODE=menu
    --env WEB_CHECK_ORIGIN=1
    --env WEB_PORT=7680
    --env ALLOW_INSECURE_WEB=1
  )

  component_probe() {
    local label="$1"
    local entrypoint="$2"
    shift 2
    local probe_name="${container}-${label}"
    local state=""

    if ! docker run -d --name "$probe_name" \
      "${strict_run_args[@]}" \
      --entrypoint "$entrypoint" \
      "$runtime_image_id" "$@" >/dev/null 2>&1; then
      echo "Strict launcher component probe $label: docker-run-failed" >&2
      return 0
    fi
    sleep 1
    state="$(docker container inspect --format \
      'status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{json .State.Error}}' \
      "$probe_name" 2>/dev/null || true)"
    printf 'Strict launcher component probe %s: %s\n' "$label" "$state" >&2
    docker logs --tail 40 "$probe_name" 2>&1 | tail -n 40 >&2 || true
    docker rm -f "$probe_name" >/dev/null 2>&1 || true
  }

  diagnostics() {
    local tini_status=0
    echo "Strict launcher candidate diagnostics:" >&2
    docker container inspect --format \
      'status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{json .State.Error}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' \
      "$container" >&2 2>/dev/null || true
    echo "Strict launcher candidate log tail (max 80 lines):" >&2
    docker logs --tail 80 "$container" 2>&1 | tail -n 80 >&2 || true

    timeout --foreground 15s docker run --rm \
      "${strict_run_args[@]}" \
      --entrypoint /usr/bin/tini \
      "$runtime_image_id" -- /bin/true >/dev/null 2>&1 || tini_status=$?
    printf 'Strict launcher component probe tini-true: exit=%s\n' "$tini_status" >&2

    component_probe env-python3 /usr/bin/env python3 --version
    component_probe python-launcher /opt/remote-dev/mise/shims/python /usr/local/bin/remote-dev-launcher
    component_probe start-script /usr/local/bin/start-remote-dev-web
    component_probe direct /usr/local/bin/remote-dev-launcher
  }

  trap cleanup EXIT INT TERM
  docker network create "$network" >/dev/null
  docker run -d --name "$container" \
    "${strict_run_args[@]}" \
    "$runtime_image_id" >/dev/null

  for _ in $(seq 1 30); do
    if [[ "$(docker container inspect --format '{{.State.Running}}' "$container" 2>/dev/null || true)" != true ]]; then
      diagnostics
      return 1
    fi
    if docker exec "$container" remote-dev-healthcheck >/dev/null 2>&1; then
      echo "Strict launcher candidate preflight: OK"
      return 0
    fi
    sleep 1
  done

  diagnostics
  return 1
)

# No candidate process executes before immutable reference, platform and labels pass.
# Keep startup diagnostics bounded to explicit config fields and file metadata; never
# dump the candidate environment or arbitrary Docker configuration. Python is supplied
# by mise through PATH, so the execution probes below validate interpreter resolution
# without assuming a distro-owned Python interpreter path.
candidate_startup_metadata

# Reproduce the strict launcher fixture independently, including its resolved local
# image config ID. On failure, isolate tini, Python resolution, the start script and
# the launcher with the same outer hardening so the larger isolation fixture cannot
# erase the cause.
strict_launcher_preflight \
  || fail "strict launcher candidate preflight failed"

# Bundled notices must validate on the exact images that may be promoted.
docker run --rm --entrypoint remote-dev-notices "$base_ref" --check
docker run --rm --entrypoint remote-dev-notices "$runtime_ref" --check

# Exercise the exact runtime candidate rather than rebuilding a second image.
docker run --rm --entrypoint /usr/local/bin/codex-smoke-test "$runtime_ref"
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

echo "Exact edge publication candidate validation: OK"
