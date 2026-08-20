#!/usr/bin/env bash
set -euo pipefail

# Exercise the current fixed-role mount boundary using only a temporary,
# synthetic data root. This test deliberately uses Docker directly rather than
# a user's Compose project so it cannot address or clean up a real deployment.

image="${1:-${REMOTE_DEV_ISOLATION_IMAGE:-remote-dev:local}}"

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: cross-service isolation test requires $1" >&2
    exit 2
  }
}

fail() {
  echo "ERROR: cross-service isolation: $*" >&2
  exit 1
}

require_command docker
require_command jq
require_command sha256sum

case "$image" in
  ''|*$'\n'*|*$'\r'*) fail "image reference is invalid" ;;
esac

image_id="$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null)" \
  || fail "local test image is unavailable: $image"
[[ "$image_id" == sha256:* ]] || fail "local test image has an invalid image ID"

test_root="$(mktemp -d "${TMPDIR:-/tmp}/remote-dev-isolation.XXXXXX")"
run_id="${test_root##*/}"
project_name="remote-dev-isolation-${run_id#remote-dev-isolation.}"
network_name="${project_name}-network"
launcher_name="${project_name}-launcher"
codex_name="${project_name}-codex"
antigravity_name="${project_name}-antigravity"
cleanup_name="${project_name}-cleanup"
readonly ownership_label="remote-dev.isolation-test"
network_id=""
launcher_id=""
codex_id=""
antigravity_id=""
cleanup_helper_id=""

validate_test_root() {
  case "$test_root" in
    "${TMPDIR:-/tmp}"/remote-dev-isolation.[[:alnum:]]*) ;;
    *)
      echo "ERROR: cross-service isolation refuses unexpected test root" >&2
      return 1
      ;;
  esac
  [[ -d "$test_root" && ! -L "$test_root" ]] || {
    echo "ERROR: cross-service isolation test root is unavailable or unsafe" >&2
    return 1
  }
}

container_label() {
  docker container inspect --format "{{ index .Config.Labels \"$ownership_label\" }}" "$1" 2>/dev/null
}

network_label() {
  docker network inspect --format "{{ index .Labels \"$ownership_label\" }}" "$1" 2>/dev/null
}

capture_owned_container_id() {
  local name="$1"
  local actual_id=""
  local observed_label=""
  if ! docker container inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  actual_id="$(docker container inspect --format '{{.Id}}' "$name")" || return 1
  observed_label="$(container_label "$name")" || return 1
  [[ "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to track an unrelated fixture container" >&2
    return 1
  }
  printf '%s\n' "$actual_id"
}

capture_owned_network_id() {
  local actual_id=""
  local observed_label=""
  if ! docker network inspect "$network_name" >/dev/null 2>&1; then
    return 0
  fi
  actual_id="$(docker network inspect --format '{{.Id}}' "$network_name")" || return 1
  observed_label="$(network_label "$network_name")" || return 1
  [[ "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to track an unrelated fixture network" >&2
    return 1
  }
  printf '%s\n' "$actual_id"
}

prepare_container_name() {
  local name="$1"
  local observed_label=""
  if ! docker container inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  observed_label="$(container_label "$name")" || {
    echo "ERROR: unable to verify existing fixture container ownership" >&2
    return 1
  }
  [[ "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to replace an unrelated container name" >&2
    return 1
  }
  docker rm -f "$name" >/dev/null || {
    echo "ERROR: failed to remove a previous owned fixture container" >&2
    return 1
  }
}

prepare_network_name() {
  local observed_label=""
  if ! docker network inspect "$network_name" >/dev/null 2>&1; then
    return 0
  fi
  observed_label="$(network_label "$network_name")" || {
    echo "ERROR: unable to verify existing fixture network ownership" >&2
    return 1
  }
  [[ "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to replace an unrelated network name" >&2
    return 1
  }
  docker network rm "$network_name" >/dev/null || {
    echo "ERROR: failed to remove a previous owned fixture network" >&2
    return 1
  }
}

remove_owned_container() {
  local name="$1"
  local expected_id="$2"
  local actual_id=""
  local observed_label=""
  [[ -n "$expected_id" ]] || return 0
  if ! docker container inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  actual_id="$(docker container inspect --format '{{.Id}}' "$name")" || return 1
  observed_label="$(container_label "$name")" || return 1
  [[ "$actual_id" == "$expected_id" && "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to remove a fixture container without matching ID and ownership" >&2
    return 1
  }
  docker rm -f "$actual_id" >/dev/null
}

remove_owned_network() {
  local actual_id=""
  local observed_label=""
  [[ -n "$network_id" ]] || return 0
  if ! docker network inspect "$network_name" >/dev/null 2>&1; then
    return 0
  fi
  actual_id="$(docker network inspect --format '{{.Id}}' "$network_name")" || return 1
  observed_label="$(network_label "$network_name")" || return 1
  [[ "$actual_id" == "$network_id" && "$observed_label" == "$run_id" ]] || {
    echo "ERROR: refusing to remove a fixture network without matching ID and ownership" >&2
    return 1
  }
  docker network rm "$actual_id" >/dev/null
}

cleanup_test_root() {
  validate_test_root || return 1
  prepare_container_name "$cleanup_name" || return 1
  cleanup_helper_id="$(docker create --pull never --name "$cleanup_name" \
    --label "$ownership_label=$run_id" \
    --network none \
    --mount "type=bind,src=$test_root,dst=/test-root" \
    --entrypoint /bin/bash \
    "$image_id" -p -c '
      set -euo pipefail
      test -d /test-root
      find -P /test-root -xdev -depth -mindepth 1 -type d -exec chmod u+rwx -- {} +
      find -P /test-root -xdev -depth -mindepth 1 -exec rm -rf -- {} +
      test -z "$(find -P /test-root -xdev -mindepth 1 -print -quit)"
    ')" || {
      echo "ERROR: failed to create the owned synthetic-root cleanup helper" >&2
      return 1
    }
  [[ "$(docker container inspect --format '{{.Id}}' "$cleanup_name")" == "$cleanup_helper_id" \
     && "$(container_label "$cleanup_name")" == "$run_id" ]] || {
    echo "ERROR: synthetic-root cleanup helper ownership could not be verified" >&2
    return 1
  }
  if ! docker start -a "$cleanup_helper_id" >/dev/null; then
    remove_owned_container "$cleanup_name" "$cleanup_helper_id" || true
    echo "ERROR: failed to clean the owned synthetic test root" >&2
    return 1
  fi
  remove_owned_container "$cleanup_name" "$cleanup_helper_id" || {
    echo "ERROR: failed to remove the owned synthetic-root cleanup helper" >&2
    return 1
  }
  rmdir -- "$test_root" || {
    echo "ERROR: owned synthetic test root remains after cleanup" >&2
    return 1
  }
}

cleanup() {
  local prior_status=$?
  local cleanup_status=0
  trap - EXIT INT TERM
  remove_owned_container "$launcher_name" "$launcher_id" || cleanup_status=1
  remove_owned_container "$codex_name" "$codex_id" || cleanup_status=1
  remove_owned_container "$antigravity_name" "$antigravity_id" || cleanup_status=1
  remove_owned_network || cleanup_status=1
  cleanup_test_root || cleanup_status=1
  if (( cleanup_status )); then
    echo "ERROR: cross-service isolation cleanup left owned resources behind" >&2
    return "$cleanup_status"
  fi
  return "$prior_status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

marker_name() {
  printf 'marker-%s-%s\n' "$1" "$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
}

make_marker() {
  local directory="$1"
  local marker="$2"
  install -d -m 0700 -- "$directory"
  printf 'synthetic-canary-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$directory/$marker"
  chmod 0600 -- "$directory/$marker"
}

assert_equal() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  [[ "$expected" == "$actual" ]] || fail "$label changed unexpectedly"
}

container_running() {
  [[ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null || true)" == true ]]
}

wait_for_health_command() {
  local name="$1"
  for _ in $(seq 1 30); do
    container_running "$name" || {
      fail "$name stopped before its role health check succeeded"
    }
    if docker exec "$name" remote-dev-healthcheck >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "$name did not satisfy its role health check"
}

assert_image_id() {
  local name="$1"
  local actual=""
  actual="$(docker inspect --format '{{.Image}}' "$name")"
  assert_equal "$name image ID" "$image_id" "$actual"
}

assert_no_broad_mounts_or_environment() {
  local name="$1"
  local role="$2"
  local inspection
  inspection="$(docker inspect "$name")"

  jq -e --arg test_root "$test_root" --arg role "$role" '
    .[0] as $container
    | ($container.Config.Env // []) as $environment
    | ($container.Mounts // []) as $mounts
    | (($environment | all(startswith("REMOTE_DEV_DATA_ROOT=") | not))
       and ($mounts | all(.Source != $test_root))
       and ($mounts | all(.Source != "/"))
       and ($mounts | all(.Source != "/root" and .Source != "/home"
                           and .Source != "/opt" and .Source != "/usr/local"))
       and ($mounts | all((.Source // "" | ascii_downcase | contains("docker.sock") | not)
                           and (.Source // "" | ascii_downcase | contains("podman.sock") | not)))
       and ($mounts | all(.Destination != "/" and .Destination != "/root" and .Destination != "/home"
                           and .Destination != "/opt" and .Destination != "/usr/local"))
       and ($mounts | all((.Destination // "" | ascii_downcase | contains("docker.sock") | not)
                           and (.Destination // "" | ascii_downcase | contains("podman.sock") | not)))
       and ($mounts | all((.Destination | test("(^|/)tmux|control"; "i")) | not))
       and ($mounts | all((.Destination != "/tmp") or (.Type == "tmpfs")))
       and (($container.HostConfig.Tmpfs // {}) | keys | all(. == "/tmp"))
       and (if $role == "launcher" then
              ($mounts | all(.Type != "bind"))
            else true
            end))
  ' <<<"$inspection" >/dev/null || fail "$role fixture has a broad, engine, parent-root, tmux/control, or data-root escape"
}

assert_mount_contract() {
  local name="$1"
  local role="$2"
  local inspection
  inspection="$(docker inspect "$name")"

  jq -e --arg root "$test_root" --arg role "$role" '
    .[0].Mounts as $mounts
    | ($mounts | map(select(.Type == "bind"))) as $binds
    | if $role == "launcher" then
        ($binds | length == 0)
      else
        (($binds | length > 0)
         and ($binds | all(.Source | startswith($root + "/")))
         and (($binds | map(.Source) | unique | length) == ($binds | length))
         and ($binds | all(.Destination != "/tmp" and .Destination != "/run"))
         and ($binds | any(.Destination == "/run/secrets/web_password" and .RW == false)))
      end
  ' <<<"$inspection" >/dev/null || fail "$role fixture mount contract is not role-private"
}

assert_distinct_agent_sources() {
  local codex_sources antigravity_sources source
  codex_sources="$(docker inspect --format '{{json .Mounts}}' "$codex_name" | jq -r '.[] | select(.Type == "bind") | .Source')"
  antigravity_sources="$(docker inspect --format '{{json .Mounts}}' "$antigravity_name" | jq -r '.[] | select(.Type == "bind") | .Source')"
  while IFS= read -r source; do
    [[ -z "$source" ]] && continue
    if grep -Fxq -- "$source" <<<"$antigravity_sources"; then
      fail "Codex and Antigravity fixtures share a writable/private mount source"
    fi
  done <<<"$codex_sources"
}

assert_path_exists() {
  local name="$1"
  local category="$2"
  local path="$3"
  docker exec "$name" test -e "$path" >/dev/null 2>&1 \
    || fail "$category is unavailable at ${path%/*} in its owning fixture"
}

assert_path_absent() {
  local name="$1"
  local category="$2"
  local path="$3"
  if docker exec "$name" test -e "$path" >/dev/null 2>&1; then
    fail "$category is visible at ${path%/*} outside its owning fixture"
  fi
}

write_owned_marker() {
  local name="$1"
  local category="$2"
  local path="$3"
  docker exec "$name" sh -c 'umask 077; printf "%s\n" "$2" > "$1"' \
    sh "$path" "synthetic-write-$run_id" >/dev/null 2>&1 \
    || fail "$category is not writable at ${path%/*} in its owning fixture"
}

measure_canary() {
  local name="$1"
  local category="$2"
  local path="$3"
  local measurement=""
  measurement="$(docker exec "$name" sh -c '
    set -eu
    test -f "$1"
    size="$(wc -c < "$1" | tr -d "[:space:]")"
    digest="$(sha256sum -- "$1" | awk "{print \$1}")"
    case "$size:$digest" in
      [0-9]*:[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
      *) exit 1 ;;
    esac
    printf "%s:%s" "$size" "$digest"
  ' sh "$path")" || fail "$category cannot be measured at ${path%/*}"
  [[ "$measurement" =~ ^[0-9]+:[0-9a-f]{64}$ ]] \
    || fail "$category returned an invalid synthetic measurement"
  printf '%s\n' "$measurement"
}

measure_host_canary() {
  local category="$1"
  local path="$2"
  local size=""
  local digest=""
  [[ -f "$path" && ! -L "$path" ]] || fail "$category source is unavailable"
  size="$(wc -c <"$path" | tr -d '[:space:]')" \
    || fail "$category source size cannot be measured"
  digest="$(sha256sum -- "$path" | awk '{print $1}')" \
    || fail "$category source hash cannot be measured"
  [[ "$size:$digest" =~ ^[0-9]+:[0-9a-f]{64}$ ]] \
    || fail "$category source returned an invalid synthetic measurement"
  printf '%s:%s\n' "$size" "$digest"
}

assert_terminal_password_canary() {
  local name="$1"
  local role="$2"
  local expected_measurement="$3"
  local actual_measurement=""
  actual_measurement="$(measure_canary "$name" "$role terminal password" "/run/secrets/web_password")"
  assert_equal "$role terminal password canary" "$expected_measurement" "$actual_measurement"
}

record_canary() {
  local records_name="$1"
  local name="$2"
  local category="$3"
  local path="$4"
  local measurement=""
  measurement="$(measure_canary "$name" "$category" "$path")"
  case "$records_name" in
    codex_invariants) codex_invariants+=("$category|$path|$measurement") ;;
    antigravity_invariants) antigravity_invariants+=("$category|$path|$measurement") ;;
    *) fail "internal unknown synthetic invariant collection" ;;
  esac
}

verify_canaries() {
  local records_name="$1"
  local name="$2"
  local record category path expected actual
  local -a records=()
  case "$records_name" in
    codex_invariants) records=("${codex_invariants[@]}") ;;
    antigravity_invariants) records=("${antigravity_invariants[@]}") ;;
    *) fail "internal unknown synthetic invariant collection" ;;
  esac
  for record in "${records[@]}"; do
    IFS='|' read -r category path expected <<<"$record"
    actual="$(measure_canary "$name" "$category" "$path")"
    assert_equal "$category synthetic canary" "$expected" "$actual"
  done
}

start_tmux_fixture() {
  local name="$1"
  local role="$2"
  local socket="isolation-${role}-${run_id#remote-dev-isolation.}"
  local session="isolation-${role}"
  docker exec "$name" tmux -L "$socket" new-session -d -s "$session" 'sleep 300' >/dev/null 2>&1 \
    || fail "$role fixture could not create its tmux socket"
  docker exec "$name" test -S "/tmp/tmux-0/$socket" >/dev/null 2>&1 \
    || fail "$role tmux socket was not private to its /tmp"
  printf '%s\n' "$socket"
}

assert_tmux_socket_private() {
  local owner="$1"
  local socket="$2"
  local category="$3"
  for observer in "$launcher_name" "$codex_name" "$antigravity_name"; do
    [[ "$observer" == "$owner" ]] && continue
    assert_path_absent "$observer" "$category tmux socket" "/tmp/tmux-0/$socket"
  done
}

declare -a codex_targets=(
  /workspace
  /root/.codex
  /root/.codex/.remote-dev-context7
  /root/.local/share/remote-dev/codex-runtime
  /root/.config/gh
  /root/.config/git
  /root/.ssh
)
declare -a antigravity_targets=(
  /workspace
  /root/.local/bin
  /root/.local/share/remote-dev/antigravity
  /root/.gemini/antigravity-cli
  /root/.config/gh
  /root/.config/git
  /root/.ssh
)
declare -a codex_categories=(workspace agent context7 runtime gh git ssh)
declare -a antigravity_categories=(workspace bin runtime vendor gh git ssh)
declare -a codex_markers=()
declare -a antigravity_markers=()
declare -a codex_invariants=()
declare -a antigravity_invariants=()

for index in "${!codex_categories[@]}"; do
  category="${codex_categories[$index]}"
  marker="$(marker_name "codex-$category")"
  codex_markers[index]="$marker"
  if [[ "$category" == context7 ]]; then
    make_marker "$test_root/codex/agent/.remote-dev-context7" "$marker"
  else
    make_marker "$test_root/codex/$category" "$marker"
  fi
done
for index in "${!antigravity_categories[@]}"; do
  category="${antigravity_categories[$index]}"
  marker="$(marker_name "antigravity-$category")"
  antigravity_markers[index]="$marker"
  make_marker "$test_root/antigravity/$category" "$marker"
done
install -d -m 0700 -- "$test_root/codex/password" "$test_root/antigravity/password"
codex_password_marker="$(marker_name codex-password)"
antigravity_password_marker="$(marker_name antigravity-password)"
codex_password_source="$test_root/codex/password/$codex_password_marker"
antigravity_password_source="$test_root/antigravity/password/$antigravity_password_marker"
printf 'synthetic-terminal-password-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$codex_password_source"
printf 'synthetic-terminal-password-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$antigravity_password_source"
chmod 0600 -- "$codex_password_source" "$antigravity_password_source"
codex_password_measurement="$(measure_host_canary 'Codex terminal password' "$codex_password_source")"
antigravity_password_measurement="$(measure_host_canary 'Antigravity terminal password' "$antigravity_password_source")"
[[ "$codex_password_measurement" != "$antigravity_password_measurement" ]] \
  || fail "role terminal password canaries are not distinct"

prepare_network_name || fail "fixture network name is already owned by another resource"
if ! network_id="$(docker network create --label "$ownership_label=$run_id" "$network_name")"; then
  network_id="$(capture_owned_network_id || true)"
  fail "failed to create fixture network"
fi
[[ "$(docker network inspect --format '{{.Id}}' "$network_name")" == "$network_id" \
   && "$(network_label "$network_name")" == "$run_id" ]] \
  || fail "fixture network ownership could not be verified"

start_launcher() {
  prepare_container_name "$launcher_name" || fail "launcher fixture name is already owned by another resource"
  if ! launcher_id="$(docker run -d --name "$launcher_name" \
    --label "$ownership_label=$run_id" \
    --network "$network_name" \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,mode=1777,size=64m \
    --env REMOTE_DEV_ROLE=launcher \
    --env REMOTE_DEV_START_MODE=menu \
    --env WEB_PORT=7680 \
    --env ALLOW_INSECURE_WEB=1 \
    "$image_id")"; then
    launcher_id="$(capture_owned_container_id "$launcher_name" || true)"
    fail "failed to start launcher fixture"
  fi
  [[ "$(docker container inspect --format '{{.Id}}' "$launcher_name")" == "$launcher_id" \
     && "$(container_label "$launcher_name")" == "$run_id" ]] \
    || fail "launcher fixture ownership could not be verified"
}

start_codex() {
  prepare_container_name "$codex_name" || fail "Codex fixture name is already owned by another resource"
  if ! codex_id="$(docker run -d --name "$codex_name" \
    --label "$ownership_label=$run_id" \
    --network "$network_name" \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,mode=1777,size=512m \
    --env REMOTE_DEV_ROLE=codex \
    --env WORKSPACE=/workspace \
    --env CODEX_HOME=/root/.codex \
    --env REMOTE_DEV_CODEX_RUNTIME_ROOT=/root/.local/share/remote-dev/codex-runtime \
    --env GH_CONFIG_DIR=/root/.config/gh \
    --env GIT_CONFIG_GLOBAL=/root/.config/git/config \
    --env WEB_PASSWORD_FILE=/run/secrets/web_password \
    --env WEB_PORT=7681 \
    --mount "type=bind,src=$test_root/codex/workspace,dst=/workspace" \
    --mount "type=bind,src=$test_root/codex/agent,dst=/root/.codex" \
    --mount "type=bind,src=$test_root/codex/runtime,dst=/root/.local/share/remote-dev/codex-runtime" \
    --mount "type=bind,src=$test_root/codex/gh,dst=/root/.config/gh" \
    --mount "type=bind,src=$test_root/codex/git,dst=/root/.config/git" \
    --mount "type=bind,src=$test_root/codex/ssh,dst=/root/.ssh" \
    --mount "type=bind,src=$codex_password_source,dst=/run/secrets/web_password,readonly" \
    "$image_id")"; then
    codex_id="$(capture_owned_container_id "$codex_name" || true)"
    fail "failed to start Codex fixture"
  fi
  [[ "$(docker container inspect --format '{{.Id}}' "$codex_name")" == "$codex_id" \
     && "$(container_label "$codex_name")" == "$run_id" ]] \
    || fail "Codex fixture ownership could not be verified"
}

start_antigravity() {
  prepare_container_name "$antigravity_name" || fail "Antigravity fixture name is already owned by another resource"
  if ! antigravity_id="$(docker run -d --name "$antigravity_name" \
    --label "$ownership_label=$run_id" \
    --network "$network_name" \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,mode=1777,size=512m \
    --env REMOTE_DEV_ROLE=antigravity \
    --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
    --env AGY_CLI_DISABLE_AUTO_UPDATE=true \
    --env WORKSPACE=/workspace \
    --env GH_CONFIG_DIR=/root/.config/gh \
    --env GIT_CONFIG_GLOBAL=/root/.config/git/config \
    --env WEB_PASSWORD_FILE=/run/secrets/web_password \
    --env WEB_PORT=7682 \
    --mount "type=bind,src=$test_root/antigravity/workspace,dst=/workspace" \
    --mount "type=bind,src=$test_root/antigravity/bin,dst=/root/.local/bin" \
    --mount "type=bind,src=$test_root/antigravity/runtime,dst=/root/.local/share/remote-dev/antigravity" \
    --mount "type=bind,src=$test_root/antigravity/vendor,dst=/root/.gemini/antigravity-cli" \
    --mount "type=bind,src=$test_root/antigravity/gh,dst=/root/.config/gh" \
    --mount "type=bind,src=$test_root/antigravity/git,dst=/root/.config/git" \
    --mount "type=bind,src=$test_root/antigravity/ssh,dst=/root/.ssh" \
    --mount "type=bind,src=$antigravity_password_source,dst=/run/secrets/web_password,readonly" \
    "$image_id")"; then
    antigravity_id="$(capture_owned_container_id "$antigravity_name" || true)"
    fail "failed to start Antigravity fixture"
  fi
  [[ "$(docker container inspect --format '{{.Id}}' "$antigravity_name")" == "$antigravity_id" \
     && "$(container_label "$antigravity_name")" == "$run_id" ]] \
    || fail "Antigravity fixture ownership could not be verified"
}

start_launcher
start_codex
start_antigravity
for name in "$launcher_name" "$codex_name" "$antigravity_name"; do
  wait_for_health_command "$name"
  assert_image_id "$name"
done
assert_no_broad_mounts_or_environment "$launcher_name" launcher
assert_no_broad_mounts_or_environment "$codex_name" codex
assert_no_broad_mounts_or_environment "$antigravity_name" antigravity
assert_mount_contract "$launcher_name" launcher
assert_mount_contract "$codex_name" codex
assert_mount_contract "$antigravity_name" antigravity
assert_distinct_agent_sources
assert_terminal_password_canary "$codex_name" Codex "$codex_password_measurement"
assert_terminal_password_canary "$antigravity_name" Antigravity "$antigravity_password_measurement"

for index in "${!codex_targets[@]}"; do
  target="${codex_targets[$index]}"
  marker="${codex_markers[$index]}"
  category="Codex ${codex_categories[$index]}"
  assert_path_exists "$codex_name" "$category" "$target/$marker"
  write_path="$target/.isolation-write-$run_id"
  write_owned_marker "$codex_name" "$category" "$write_path"
  record_canary codex_invariants "$codex_name" "$category marker" "$target/$marker"
  record_canary codex_invariants "$codex_name" "$category write marker" "$write_path"
  assert_path_absent "$antigravity_name" "$category" "$target/$marker"
  assert_path_absent "$launcher_name" "$category" "$target/$marker"
done
for index in "${!antigravity_targets[@]}"; do
  target="${antigravity_targets[$index]}"
  marker="${antigravity_markers[$index]}"
  category="Antigravity ${antigravity_categories[$index]}"
  assert_path_exists "$antigravity_name" "$category" "$target/$marker"
  write_path="$target/.isolation-write-$run_id"
  write_owned_marker "$antigravity_name" "$category" "$write_path"
  record_canary antigravity_invariants "$antigravity_name" "$category marker" "$target/$marker"
  record_canary antigravity_invariants "$antigravity_name" "$category write marker" "$write_path"
  assert_path_absent "$codex_name" "$category" "$target/$marker"
  assert_path_absent "$launcher_name" "$category" "$target/$marker"
done
assert_path_absent "$launcher_name" "agent terminal password source" "/run/secrets/web_password"

codex_socket="$(start_tmux_fixture "$codex_name" codex)"
antigravity_socket="$(start_tmux_fixture "$antigravity_name" antigravity)"
assert_tmux_socket_private "$codex_name" "$codex_socket" Codex
assert_tmux_socket_private "$antigravity_name" "$antigravity_socket" Antigravity

if docker exec "$antigravity_name" run-antigravity >/dev/null 2>&1; then
  fail "missing synthetic Antigravity runtime unexpectedly launched"
fi
verify_canaries codex_invariants "$codex_name"
assert_terminal_password_canary "$codex_name" Codex "$codex_password_measurement"
assert_terminal_password_canary "$antigravity_name" Antigravity "$antigravity_password_measurement"
assert_equal "Codex terminal password canary" "$codex_password_measurement" \
  "$(measure_host_canary 'Codex terminal password' "$codex_password_source")"
assert_equal "Antigravity terminal password canary" "$antigravity_password_measurement" \
  "$(measure_host_canary 'Antigravity terminal password' "$antigravity_password_source")"
wait_for_health_command "$launcher_name"
wait_for_health_command "$codex_name"
wait_for_health_command "$antigravity_name"

remove_owned_container "$codex_name" "$codex_id" \
  || fail "failed to remove the owned Codex fixture for recreation"
start_codex
wait_for_health_command "$codex_name"
assert_image_id "$codex_name"
assert_no_broad_mounts_or_environment "$codex_name" codex
assert_mount_contract "$codex_name" codex
verify_canaries codex_invariants "$codex_name"
assert_terminal_password_canary "$codex_name" Codex "$codex_password_measurement"
assert_terminal_password_canary "$antigravity_name" Antigravity "$antigravity_password_measurement"
assert_equal "Codex terminal password canary" "$codex_password_measurement" \
  "$(measure_host_canary 'Codex terminal password' "$codex_password_source")"
verify_canaries antigravity_invariants "$antigravity_name"
assert_equal "Antigravity terminal password canary" "$antigravity_password_measurement" \
  "$(measure_host_canary 'Antigravity terminal password' "$antigravity_password_source")"
wait_for_health_command "$launcher_name"
wait_for_health_command "$antigravity_name"

remove_owned_container "$antigravity_name" "$antigravity_id" \
  || fail "failed to remove the owned Antigravity fixture for recreation"
start_antigravity
wait_for_health_command "$antigravity_name"
assert_image_id "$antigravity_name"
assert_no_broad_mounts_or_environment "$antigravity_name" antigravity
assert_mount_contract "$antigravity_name" antigravity
assert_distinct_agent_sources
verify_canaries codex_invariants "$codex_name"
assert_terminal_password_canary "$codex_name" Codex "$codex_password_measurement"
assert_terminal_password_canary "$antigravity_name" Antigravity "$antigravity_password_measurement"
assert_equal "Codex terminal password canary" "$codex_password_measurement" \
  "$(measure_host_canary 'Codex terminal password' "$codex_password_source")"
assert_equal "Antigravity terminal password canary" "$antigravity_password_measurement" \
  "$(measure_host_canary 'Antigravity terminal password' "$antigravity_password_source")"
wait_for_health_command "$launcher_name"
wait_for_health_command "$codex_name"

echo "Cross-service synthetic isolation canaries: OK"
