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

cleanup() {
  for name in "$launcher_name" "$codex_name" "$antigravity_name"; do
    docker container inspect "$name" >/dev/null 2>&1 \
      && docker rm -f "$name" >/dev/null 2>&1 || true
  done
  docker network inspect "$network_name" >/dev/null 2>&1 \
    && docker network rm "$network_name" >/dev/null 2>&1 || true
  case "$test_root" in
    "${TMPDIR:-/tmp}"/remote-dev-isolation.*) rm -rf -- "$test_root" ;;
    *) echo "ERROR: refusing to remove unexpected test root" >&2 ;;
  esac
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
  : >"$directory/$marker"
  chmod 0600 -- "$directory/$marker"
}

fingerprint_tree() {
  local directory="$1"
  (
    cd "$directory"
    while IFS= read -r -d '' path; do
      printf '%s\0' "$path"
      sha256sum -- "$path" | awk '{print $1}'
    done < <(find . -type f -print0 | LC_ALL=C sort -z)
  ) | sha256sum | awk '{print $1}'
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
  docker exec "$name" sh -c 'umask 077; : > "$1"' sh "$path" >/dev/null 2>&1 \
    || fail "$category is not writable at ${path%/*} in its owning fixture"
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
printf 'synthetic-terminal-password\n' >"$codex_password_source"
printf 'synthetic-terminal-password\n' >"$antigravity_password_source"
chmod 0600 -- "$codex_password_source" "$antigravity_password_source"

docker network create --label "remote-dev.isolation-test=$run_id" "$network_name" >/dev/null

start_launcher() {
  docker run -d --name "$launcher_name" \
    --label "remote-dev.isolation-test=$run_id" \
    --network "$network_name" \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,mode=1777,size=64m \
    --env REMOTE_DEV_ROLE=launcher \
    --env REMOTE_DEV_START_MODE=menu \
    --env WEB_PORT=7680 \
    --env ALLOW_INSECURE_WEB=1 \
    "$image" >/dev/null
}

start_codex() {
  docker run -d --name "$codex_name" \
    --label "remote-dev.isolation-test=$run_id" \
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
    "$image" >/dev/null
}

start_antigravity() {
  docker run -d --name "$antigravity_name" \
    --label "remote-dev.isolation-test=$run_id" \
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
    "$image" >/dev/null
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

for index in "${!codex_targets[@]}"; do
  target="${codex_targets[$index]}"
  marker="${codex_markers[$index]}"
  category="Codex ${codex_categories[$index]}"
  assert_path_exists "$codex_name" "$category" "$target/$marker"
  write_owned_marker "$codex_name" "$category" "$target/.isolation-write-$run_id"
  assert_path_absent "$antigravity_name" "$category" "$target/$marker"
  assert_path_absent "$launcher_name" "$category" "$target/$marker"
done
for index in "${!antigravity_targets[@]}"; do
  target="${antigravity_targets[$index]}"
  marker="${antigravity_markers[$index]}"
  category="Antigravity ${antigravity_categories[$index]}"
  assert_path_exists "$antigravity_name" "$category" "$target/$marker"
  write_owned_marker "$antigravity_name" "$category" "$target/.isolation-write-$run_id"
  assert_path_absent "$codex_name" "$category" "$target/$marker"
  assert_path_absent "$launcher_name" "$category" "$target/$marker"
done
assert_path_absent "$launcher_name" "agent terminal password source" "/run/secrets/web_password"

codex_socket="$(start_tmux_fixture "$codex_name" codex)"
antigravity_socket="$(start_tmux_fixture "$antigravity_name" antigravity)"
assert_tmux_socket_private "$codex_name" "$codex_socket" Codex
assert_tmux_socket_private "$antigravity_name" "$antigravity_socket" Antigravity

codex_stable_before_failure="$(fingerprint_tree "$test_root/codex")"
launcher_health_before_failure="$(docker inspect --format '{{.State.Running}}' "$launcher_name")"
if docker exec "$antigravity_name" run-antigravity >/dev/null 2>&1; then
  fail "missing synthetic Antigravity runtime unexpectedly launched"
fi
assert_equal "Codex state after failed Antigravity launch" \
  "$codex_stable_before_failure" "$(fingerprint_tree "$test_root/codex")"
assert_equal "launcher availability after failed Antigravity launch" true "$launcher_health_before_failure"
wait_for_health_command "$launcher_name"
wait_for_health_command "$codex_name"
wait_for_health_command "$antigravity_name"

antigravity_stable_before_codex_recreate="$(fingerprint_tree "$test_root/antigravity")"
docker rm -f "$codex_name" >/dev/null
start_codex
wait_for_health_command "$codex_name"
assert_image_id "$codex_name"
assert_no_broad_mounts_or_environment "$codex_name" codex
assert_mount_contract "$codex_name" codex
assert_equal "Antigravity state after Codex recreation" \
  "$antigravity_stable_before_codex_recreate" "$(fingerprint_tree "$test_root/antigravity")"
wait_for_health_command "$launcher_name"
wait_for_health_command "$antigravity_name"

codex_stable_before_antigravity_recreate="$(fingerprint_tree "$test_root/codex")"
docker rm -f "$antigravity_name" >/dev/null
start_antigravity
wait_for_health_command "$antigravity_name"
assert_image_id "$antigravity_name"
assert_no_broad_mounts_or_environment "$antigravity_name" antigravity
assert_mount_contract "$antigravity_name" antigravity
assert_distinct_agent_sources
assert_equal "Codex state after Antigravity recreation" \
  "$codex_stable_before_antigravity_recreate" "$(fingerprint_tree "$test_root/codex")"
wait_for_health_command "$launcher_name"
wait_for_health_command "$codex_name"

echo "Cross-service synthetic isolation canaries: OK"
