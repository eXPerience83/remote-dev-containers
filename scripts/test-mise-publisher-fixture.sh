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

strict=(
  --rm
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

diagnostics() {
  echo "Publisher-equivalent mise diagnostics (safe fields only):" >&2
  docker run "${strict[@]}" \
    --entrypoint /bin/bash \
    "$image" -c '
      printf "uid=%s gid=%s cwd=%s\n" "$(id -u)" "$(id -g)" "$PWD"
      for name in HOME MISE_SYSTEM_CONFIG_DIR MISE_SYSTEM_CONFIG_FILE MISE_DATA_DIR MISE_CACHE_DIR PATH; do
        printf "%s=%s\n" "$name" "${!name-<unset>}"
      done
      for path in /etc /etc/mise /etc/mise/config.toml /etc/mise/config.lock /opt/remote-dev/mise /opt/remote-dev/mise/installs /opt/remote-dev/mise/shims; do
        /usr/bin/stat -Lc "%n uid=%u gid=%g mode=%a" "$path" || true
      done
      /usr/local/bin/mise --version || true
      /usr/local/bin/mise config get --system tools.python || true
      /usr/local/bin/mise which python || true
    ' 2>&1 | tail -n 80 >&2 || true
}

fail() {
  echo "ERROR: publisher-equivalent mise regression: $*" >&2
  diagnostics
  exit 1
}

mise_dir_mode="$(docker run "${strict[@]}" \
  --entrypoint /usr/bin/stat \
  "$image" -Lc '%a' /etc/mise)" \
  || fail "could not inspect /etc/mise as the unprivileged runtime user"
[[ "$mise_dir_mode" == 755 ]] \
  || fail "/etc/mise mode is $mise_dir_mode, expected 755"

docker run "${strict[@]}" \
  --entrypoint /bin/bash \
  "$image" -c 'test -r /etc/mise/config.toml && test -r /etc/mise/config.lock' \
  >/dev/null 2>&1 \
  || fail "canonical system config or lockfile is not readable as UID 65532"

docker run "${strict[@]}" \
  --entrypoint /usr/local/bin/mise \
  "$image" config get --system tools.python \
  >/dev/null 2>&1 \
  || fail "mise cannot read tools.python from the system config as UID 65532"

docker run "${strict[@]}" \
  --entrypoint /usr/bin/env \
  "$image" python3 --version \
  >/dev/null 2>&1 \
  || fail "python3 shim does not resolve under the exact publisher isolation fixture"

echo "Publisher-equivalent non-root mise system config and shim resolution: OK"
