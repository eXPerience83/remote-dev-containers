#!/usr/bin/env bash
set -euo pipefail

if (( $# != 1 )); then
  echo "Usage: $0 <runtime-image>" >&2
  exit 2
fi

image="$1"
suffix="${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-0}-${RANDOM}"
network="remote-dev-local-mise-${suffix}"

cleanup() {
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create "$network" >/dev/null

common=(
  --rm
  --user 65532:65532
  --read-only
  --cap-drop ALL
  --pids-limit 64
  --security-opt no-new-privileges:true
  --ipc private
  --env REMOTE_DEV_ROLE=launcher
  --env REMOTE_DEV_START_MODE=menu
  --env WEB_CHECK_ORIGIN=1
  --env WEB_PORT=7680
  --env ALLOW_INSECURE_WEB=1
  --entrypoint /usr/bin/env
)

run_probe() {
  local label="$1"
  shift
  local status=0
  if docker run "${common[@]}" "$@" "$image" python3 --version >/dev/null 2>"${RUNNER_TEMP:-/tmp}/remote-dev-mise-${suffix}-${label}.log"; then
    printf 'Publisher-equivalent mise probe %-18s OK\n' "$label"
    return 0
  else
    status=$?
    printf 'Publisher-equivalent mise probe %-18s FAILED exit=%s\n' "$label" "$status" >&2
    tail -n 20 "${RUNNER_TEMP:-/tmp}/remote-dev-mise-${suffix}-${label}.log" >&2 || true
    return "$status"
  fi
}

# Keep each comparison bounded to one changed isolation dimension. These probes
# diagnose the gap between the existing non-root local smoke and the exact edge
# publisher fixture without weakening the publisher gate itself.
exact_status=0
run_probe exact \
  --network "$network" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755 \
  || exact_status=$?

run_probe no-tmpfs --network "$network" || true
run_probe tmp-only \
  --network "$network" \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  || true
run_probe run-only \
  --network "$network" \
  --tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755 \
  || true
run_probe network-none \
  --network none \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755 \
  || true

if (( exact_status != 0 )); then
  echo "Publisher-equivalent mise selected environment diagnostics:" >&2
  docker run "${common[@]}" \
    --network "$network" \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
    --tmpfs /run:rw,noexec,nosuid,nodev,size=16m,mode=755 \
    --entrypoint /bin/bash \
    "$image" -c '
      printf "uid=%s gid=%s cwd=%s\n" "$(id -u)" "$(id -g)" "$PWD"
      for name in HOME MISE_SYSTEM_CONFIG_DIR MISE_SYSTEM_CONFIG_FILE MISE_DATA_DIR MISE_CACHE_DIR PATH; do
        printf "%s=%s\n" "$name" "${!name-<unset>}"
      done
      for path in /etc /etc/mise /etc/mise/config.toml /etc/mise/config.lock /opt /opt/remote-dev /opt/remote-dev/mise /opt/remote-dev/mise/installs /opt/remote-dev/mise/shims; do
        /usr/bin/stat -Lc "%n uid=%u gid=%g mode=%a" "$path" || true
      done
      if [[ -r /etc/mise/config.toml ]]; then
        echo "system-config-readable=yes"
        /usr/bin/sha256sum /etc/mise/config.toml || true
      else
        echo "system-config-readable=no"
      fi
      if [[ -r /etc/mise/config.lock ]]; then
        echo "system-lock-readable=yes"
        /usr/bin/sha256sum /etc/mise/config.lock || true
      else
        echo "system-lock-readable=no"
      fi
      /usr/local/bin/mise --version || true
      /usr/local/bin/mise config get --system tools.python || true
      /usr/local/bin/mise config ls || true
      /usr/local/bin/mise ls --current || true
      /usr/local/bin/mise which python || true
    ' 2>&1 | tail -n 100 >&2 || true
  exit "$exact_status"
fi

echo "Publisher-equivalent non-root mise shim resolution: OK"
