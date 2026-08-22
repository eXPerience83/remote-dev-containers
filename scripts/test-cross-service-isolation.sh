#!/usr/bin/env bash
set -euo pipefail

# Exercise the current fixed-role mount boundary using only a temporary,
# synthetic data root. This test deliberately uses Docker directly rather than
# a user's Compose project so it cannot address or clean up a real deployment.

image="${1:-${REMOTE_DEV_ISOLATION_IMAGE:-remote-dev:local}}"
source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

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
require_command timeout

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
readonly cleanup_helper_timeout_seconds=30
readonly docker_exec_timeout_seconds=30
readonly docker_exec_kill_after_seconds=5

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

owned_container_matches() {
  local name="$1"
  local expected_id="$2"
  local actual_id=""
  local observed_label=""
  [[ -n "$expected_id" ]] || return 1
  actual_id="$(docker container inspect --format '{{.Id}}' "$name" 2>/dev/null)" || return 1
  observed_label="$(container_label "$name")" || return 1
  [[ "$actual_id" == "$expected_id" && "$observed_label" == "$run_id" ]]
}

remove_owned_container() {
  local name="$1"
  local expected_id="$2"
  [[ -n "$expected_id" ]] || return 0
  if ! docker container inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  owned_container_matches "$name" "$expected_id" || {
    echo "ERROR: refusing to remove a fixture container without matching ID and ownership" >&2
    return 1
  }
  docker rm -f "$expected_id" >/dev/null
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

run_cleanup_helper() {
  local helper_state=""
  local attempt=0

  owned_container_matches "$cleanup_name" "$cleanup_helper_id" || {
    echo "ERROR: synthetic-root cleanup helper ownership could not be verified before start" >&2
    return 1
  }
  docker start "$cleanup_helper_id" >/dev/null || {
    echo "ERROR: failed to start the owned synthetic-root cleanup helper" >&2
    return 1
  }

  for ((attempt = 0; attempt < cleanup_helper_timeout_seconds; attempt++)); do
    helper_state="$(docker container inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$cleanup_helper_id" 2>/dev/null)" || {
      echo "ERROR: synthetic-root cleanup helper state could not be inspected" >&2
      return 1
    }
    case "$helper_state" in
      exited:0) return 0 ;;
      exited:*)
        echo "ERROR: owned synthetic-root cleanup helper exited unsuccessfully" >&2
        return 1
        ;;
      created:*|running:*) sleep 1 ;;
      *)
        echo "ERROR: owned synthetic-root cleanup helper entered an unexpected state" >&2
        return 1
        ;;
    esac
  done

  helper_state="$(docker container inspect --format '{{.State.Status}}:{{.State.ExitCode}}' "$cleanup_helper_id" 2>/dev/null)" || {
    echo "ERROR: synthetic-root cleanup helper state could not be inspected after timeout" >&2
    return 1
  }
  case "$helper_state" in
    exited:0) return 0 ;;
    exited:*)
      echo "ERROR: owned synthetic-root cleanup helper exited unsuccessfully" >&2
      return 1
      ;;
  esac
  owned_container_matches "$cleanup_name" "$cleanup_helper_id" || {
    echo "ERROR: synthetic-root cleanup helper ownership could not be verified before timeout kill" >&2
    return 1
  }
  docker kill "$cleanup_helper_id" >/dev/null || {
    echo "ERROR: failed to stop the timed-out owned synthetic-root cleanup helper" >&2
    return 1
  }
  echo "ERROR: owned synthetic-root cleanup helper timed out" >&2
  return 1
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
  owned_container_matches "$cleanup_name" "$cleanup_helper_id" || {
    echo "ERROR: synthetic-root cleanup helper ownership could not be verified" >&2
    return 1
  }
  if ! run_cleanup_helper; then
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
    exit 1
  fi
  exit "$prior_status"
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

docker_exec() {
  local status=0
  timeout --foreground --kill-after="${docker_exec_kill_after_seconds}s" "${docker_exec_timeout_seconds}s" \
    docker exec "$@" || status=$?
  case "$status" in
    124) echo "ERROR: docker exec timed out after ${docker_exec_timeout_seconds}s" >&2 ;;
    125) echo "ERROR: docker exec timeout invocation failed" >&2 ;;
    137) echo "ERROR: docker exec required KILL escalation" >&2 ;;
  esac
  return "$status"
}

docker_exec_infrastructure_failure() {
  case "$1" in
    124|125|137) return 0 ;;
    *) return 1 ;;
  esac
}

wait_for_health_command() {
  local name="$1"
  local status=0
  for _ in $(seq 1 30); do
    container_running "$name" || {
      fail "$name stopped before its role health check succeeded"
    }
    if docker_exec "$name" remote-dev-healthcheck >/dev/null 2>&1; then
      return 0
    else
      status=$?
      if docker_exec_infrastructure_failure "$status"; then
        fail "$name role health check docker exec failed"
      fi
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
       and (($container.HostConfig.Tmpfs // {}) | keys | sort == ["/run", "/tmp"])
       and (if $role == "launcher" then
              (($mounts | map(select(.Type == "bind"))) as $binds
               | ($binds | length == 1)
               and ($binds[0].Source == ($test_root + "/launcher/password/web_password"))
               and ($binds[0].Destination == "/run/secrets/launcher_password")
               and ($binds[0].RW == false))
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
        (($binds | length == 1)
         and ($binds[0].Source == ($root + "/launcher/password/web_password"))
         and ($binds[0].Destination == "/run/secrets/launcher_password")
         and ($binds[0].RW == false))
      else
        (($binds | length > 0)
         and ($binds | all(.Source | startswith($root + "/")))
         and (($binds | map(.Source) | unique | length) == ($binds | length))
         and ($binds | all(.Destination != "/tmp" and .Destination != "/run"))
         and ($binds | any(.Destination == "/run/secrets/web_password" and .RW == false)))
      end
  ' <<<"$inspection" >/dev/null || fail "$role fixture mount contract is not role-private"
}

assert_hardening_contract() {
  local name="$1"
  local role="$2"
  local inspection
  inspection="$(docker inspect "$name")"

  if ! jq -e --arg role "$role" '
    .[0].HostConfig as $host
    | (if $role == "launcher" then
         ["DAC_READ_SEARCH", "SETGID", "SETUID"]
       else
         ["CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETGID", "SETUID"]
       end) as $expected_caps
    | (if $role == "launcher" then 64 else 1024 end) as $expected_pids
    | (if $role == "launcher" then "size=64m"
       else "size=512m"
       end) as $tmp_size
    | (if $role == "launcher" then "size=16m"
       elif $role == "codex" then "size=1536m"
       else "size=64m"
       end) as $run_size
    | (($host.Tmpfs // {}) as $tmpfs
       | ($tmpfs | keys | sort) == ["/run", "/tmp"]
       and (($tmpfs["/tmp"] | split(",")) as $options
            | (["rw", "noexec", "nosuid", "nodev", $tmp_size, "mode=1777"]
               | all(. as $required | $options | index($required) != null))
            and ($options | length == 6))
       and (($tmpfs["/run"] | split(",")) as $options
            | (["rw", "nosuid", "nodev", $run_size, "mode=755"]
               | all(. as $required | $options | index($required) != null))
            and ($options | length == 5)))
    and ($host.ReadonlyRootfs == true)
    and (($host.CapDrop // []) == ["ALL"])
    and ((($host.CapAdd // []) | sort) == ($expected_caps | sort))
    and ($host.PidsLimit == $expected_pids)
    and ($host.Privileged == false)
    and (($host.PidMode // "") != "host")
    and (($host.NetworkMode // "") != "host")
    and (($host.GroupAdd // []) | length == 0)
    and (($host.SecurityOpt // []) == ["no-new-privileges:true"])
  ' <<<"$inspection" >/dev/null; then
    jq '.[0] | {
      readonly_rootfs: .HostConfig.ReadonlyRootfs,
      cap_drop: .HostConfig.CapDrop,
      cap_add: .HostConfig.CapAdd,
      pids_limit: .HostConfig.PidsLimit,
      privileged: .HostConfig.Privileged,
      pid_mode: .HostConfig.PidMode,
      network_mode: .HostConfig.NetworkMode,
      group_add: .HostConfig.GroupAdd,
      security_opt: .HostConfig.SecurityOpt,
      tmpfs: .HostConfig.Tmpfs
    }' <<<"$inspection" >&2
    fail "$role fixture differs from the reviewed hardening contract"
  fi
}

assert_runtime_mount_options() {
  local name="$1"
  local role="$2"
  docker_exec "$name" sh -c '
    set -eu
    mount_options() {
      awk -v target="$1" '\''$2 == target { print $4 }'\'' /proc/mounts
    }
    tmp_options="$(mount_options /tmp)"
    run_options="$(mount_options /run)"
    for required in rw noexec nosuid nodev; do
      case ",$tmp_options," in
        *",$required,"*) ;;
        *) exit 1 ;;
      esac
    done
    for required in rw nosuid nodev; do
      case ",$run_options," in
        *",$required,"*) ;;
        *) exit 1 ;;
      esac
    done
    case ",$run_options," in
      *,noexec,*) exit 1 ;;
    esac
  ' >/dev/null 2>&1 || fail "$role fixture runtime tmpfs options are not enforced"
}

assert_launcher_runtime_identity() {
  docker_exec "$launcher_name" sh -c '
    set -eu
    pid="$(pgrep -f "[/]usr/local/bin/remote-dev-launcher" | head -n 1)"
    test -n "$pid"
    status="/proc/$pid/status"
    awk '\''$1 == "Uid:" { exit !($2 == 65532 && $3 == 65532 && $4 == 65532 && $5 == 65532) }'\'' "$status"
    awk '\''$1 == "Gid:" { exit !($2 == 65532 && $3 == 65532 && $4 == 65532 && $5 == 65532) }'\'' "$status"
    awk '\''$1 == "Groups:" { exit !(NF == 1) }'\'' "$status"
    grep -Eq '\''^CapEff:[[:space:]]+0+$'\'' "$status"
    grep -Eq '\''^NoNewPrivs:[[:space:]]+1$'\'' "$status"
  ' >/dev/null 2>&1 || fail "launcher HTTP process did not retain its permanent unprivileged boundary"
}

assert_agent_runtime_identity() {
  local name="$1"
  local role="$2"
  docker_exec "$name" sh -c '
    set -eu
    pid="$(pgrep -xo ttyd)"
    status="/proc/$pid/status"
    awk '\''$1 == "Uid:" { exit !($2 == 0 && $3 == 0 && $4 == 0 && $5 == 0) }'\'' "$status"
    awk '\''$1 == "Gid:" { exit !($2 == 0 && $3 == 0 && $4 == 0 && $5 == 0) }'\'' "$status"
    awk '\''$1 == "Groups:" { exit !(NF == 1) }'\'' "$status"
    grep -Eqi '\''^CapEff:[[:space:]]+0*eb$'\'' "$status"
    grep -Eq '\''^NoNewPrivs:[[:space:]]+1$'\'' "$status"
    probe=/workspace/.hardening-capability-probe
    test -f "$probe"
    chown 65534:65534 "$probe"
    chmod 000 "$probe"
    printf probe >"$probe"
    chmod 0600 "$probe"
    chown 0:0 "$probe"
    setpriv --reuid 65534 --regid 65534 --clear-groups sh -c '\''
      test "$(id -u)" = 65534
      test "$(id -g)" = 65534
      test "$(id -G)" = 65534
    '\''
    setpriv --reuid 65534 --regid 65534 --clear-groups sleep 30 &
    child=$!
    kill "$child"
    child_status=0
    wait "$child" || child_status=$?
    test "$child_status" = 143
  ' >/dev/null 2>&1 || fail "$role fixture did not preserve the reviewed root and unprivileged-child identities"
}

assert_launcher_http_security() {
  local status=""
  status="$(docker_exec "$launcher_name" curl --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:7680/healthz)" \
    || fail "launcher secret-free health endpoint could not be reached"
  [[ "$status" == 200 ]] || fail "launcher secret-free health endpoint returned an unexpected status"

  status="$(docker_exec "$launcher_name" curl --silent --output /dev/null --write-out '%{http_code}' \
    http://127.0.0.1:7680/)" \
    || fail "launcher unauthenticated request could not be evaluated"
  [[ "$status" == 401 ]] || fail "launcher did not enforce Basic authentication"

  status="$(docker_exec "$launcher_name" curl --silent --output /dev/null --write-out '%{http_code}' \
    --user "isolation-launcher:$launcher_password" \
    --header 'Origin: http://127.0.0.1:7680' \
    http://127.0.0.1:7680/)" \
    || fail "launcher authenticated request could not be evaluated"
  [[ "$status" == 200 ]] || fail "launcher rejected its synthetic authenticated request"

  status="$(docker_exec "$launcher_name" curl --silent --output /dev/null --write-out '%{http_code}' \
    --user "isolation-launcher:$launcher_password" \
    --header 'Origin: https://invalid.example' \
    http://127.0.0.1:7680/)" \
    || fail "launcher origin rejection request could not be evaluated"
  [[ "$status" == 403 ]] || fail "launcher did not reject a cross-origin request"

  status="$(docker_exec "$launcher_name" curl --silent --output /dev/null --write-out '%{http_code}' \
    --request POST \
    --user "isolation-launcher:$launcher_password" \
    http://127.0.0.1:7680/)" \
    || fail "launcher method rejection request could not be evaluated"
  [[ "$status" == 405 ]] || fail "launcher did not reject a state-changing method"

  docker_exec "$launcher_name" sh -c '
    set -eu
    headers="$(mktemp /tmp/launcher-headers.XXXXXX)"
    trap '\''rm -f -- "$headers"'\'' EXIT
    curl --fail --silent --show-error --dump-header "$headers" --output /dev/null \
      --user "$1:$2" --header "Origin: http://127.0.0.1:7680" \
      http://127.0.0.1:7680/
    grep -Fqi -- "$3" "$headers"
  ' sh isolation-launcher "$launcher_password" "Content-Security-Policy: default-src 'none'" \
    >/dev/null 2>&1 \
    || fail "launcher response did not retain its restrictive CSP"
}

assert_read_only_rootfs() {
  local name="$1"
  local role="$2"
  docker_exec "$name" sh -c '
    path="/etc/.remote-dev-read-only-probe-$$"
    if printf probe >"$path" 2>/dev/null; then
      rm -f -- "$path"
      exit 1
    fi
  ' >/dev/null 2>&1 || fail "$role fixture unexpectedly permits writes to the immutable root filesystem"
}

assert_codex_toolchain_workflow() {
  docker_exec "$codex_name" bash -c '
    set -euo pipefail
    project="/workspace/hardening-toolchain"
    rm -rf -- "$project"
    mkdir -p "$project/local-dependency"
    cd "$project"

    printf "value = 1\n" > module.py
    printf "from module import value\nassert value == 1\n" > test_module.py
    python -m py_compile module.py test_module.py
    python test_module.py
    python -m venv .venv
    .venv/bin/python -c "import sys; assert sys.prefix.endswith(\"/.venv\")"
    uv venv --offline .uv-venv >/dev/null

    printf '\''{"name":"remote-dev-local-dependency","version":"1.0.0","main":"index.js"}\n'\'' \
      > local-dependency/package.json
    printf '\''module.exports = 42;\n'\'' > local-dependency/index.js
    printf '\''{"name":"remote-dev-toolchain-smoke","version":"1.0.0","private":true}\n'\'' \
      > package.json
    npm install --offline --ignore-scripts --no-audit --no-fund ./local-dependency >/dev/null
    node -e '\''if (require("remote-dev-local-dependency") !== 42) process.exit(1)'\''
    test -d "$NPM_CONFIG_CACHE"
    test -d "$UV_CACHE_DIR"

    printf '\''#include <stdio.h>\nint main(void) { return puts("ok") < 0; }\n'\'' > smoke.c
    printf '\''smoke: smoke.c\n\t$(CC) -Wall -Wextra -Werror -o $@ $<\n'\'' > Makefile
    make >/dev/null
    test "$(./smoke)" = ok

    git init -q
    git config user.name "Synthetic Test"
    git config user.email "synthetic@example.invalid"
    git add module.py test_module.py package.json package-lock.json smoke.c Makefile
    git status --porcelain | grep -q .

    socket="hardening-toolchain"
    tmux -L "$socket" new-session -d -s hardening "sleep 30"
    tmux -L "$socket" has-session -t hardening
    tmux -L "$socket" list-sessions | grep -q '\''^hardening:'\''
    tmux -L "$socket" kill-server
  ' >/dev/null 2>&1 || fail "hardened Codex fixture could not complete the offline development-toolchain workflow"
  wait_for_health_command "$codex_name"
}

assert_hardened_antigravity_host_fixtures() {
  local fixture_root="/workspace/hardening-antigravity-fixtures"
  local fixture_tmp="$fixture_root/tmp"
  local copy_status=0
  docker_exec "$antigravity_name" install -d -m 0755 \
    "$fixture_root/scripts" "$fixture_tmp" >/dev/null 2>&1 \
    || fail "hardened Antigravity fixture roots could not be prepared"
  docker_exec "$antigravity_name" chown 65534:65534 "$fixture_tmp" >/dev/null 2>&1 \
    || fail "Antigravity unprivileged fixture staging ownership could not be prepared"
  docker_exec "$antigravity_name" chmod 0700 "$fixture_tmp" >/dev/null 2>&1 \
    || fail "Antigravity unprivileged fixture staging mode could not be prepared"
  timeout --foreground --kill-after="${docker_exec_kill_after_seconds}s" \
    "${docker_exec_timeout_seconds}s" \
    docker cp "$source_root/scripts/." "$antigravity_name:$fixture_root/scripts" \
    >/dev/null 2>&1 || copy_status=$?
  case "$copy_status" in
    0) ;;
    124) fail "Antigravity fixture copy timed out" ;;
    125) fail "Antigravity fixture copy timeout invocation failed" ;;
    137) fail "Antigravity fixture copy required KILL escalation" ;;
    *) fail "Antigravity fixture copy failed" ;;
  esac
  docker_exec "$antigravity_name" chmod -R a+rX "$fixture_root/scripts" >/dev/null 2>&1 \
    || fail "Antigravity copied fixture sources could not be made readable"

  # These host-safe harnesses intentionally shadow curl/readelf with synthetic
  # binaries. The production root manager correctly ignores such PATH shadows,
  # so exercise the harnesses as the same fixed unprivileged identity used for
  # candidate execution while the surrounding container remains hardened.
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-antigravity-runtime.sh" >/dev/null 2>&1 \
    || fail "Antigravity runtime/admission fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-antigravity-security-regressions.sh" >/dev/null 2>&1 \
    || fail "Antigravity security fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-antigravity-repair-download-hardening.sh" >/dev/null 2>&1 \
    || fail "Antigravity repair fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-antigravity-staging-wrappers.sh" >/dev/null 2>&1 \
    || fail "Antigravity private-staging fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-antigravity-redirects.sh" >/dev/null 2>&1 \
    || fail "Antigravity installer-origin fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    python "$fixture_root/scripts/test-antigravity-oauth.py" >/dev/null 2>&1 \
    || fail "Antigravity OAuth fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    python "$fixture_root/scripts/test-antigravity-picker.py" >/dev/null 2>&1 \
    || fail "Antigravity picker fixture failed under hardening"
  docker_exec --user 65534:65534 "$antigravity_name" env TMPDIR="$fixture_tmp" \
    bash "$fixture_root/scripts/test-run-antigravity-picker.sh" >/dev/null 2>&1 \
    || fail "Antigravity resume helper fixture failed under hardening"

  docker_exec "$antigravity_name" rm -rf -- "$fixture_root" "$fixture_tmp" >/dev/null 2>&1 \
    || fail "Antigravity hardened fixtures did not clean up"
  wait_for_health_command "$antigravity_name"
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
  docker_exec "$name" test -e "$path" >/dev/null 2>&1 \
    || fail "$category is unavailable at ${path%/*} in its owning fixture"
}

assert_path_absent() {
  local name="$1"
  local category="$2"
  local path="$3"
  local output=""
  local status=0
  output="$(docker_exec "$name" sh -c '
    if test ! -e "$1"; then
      printf absent
      exit 0
    fi
    printf present
    exit 1
  ' sh "$path" 2>&1)" || status=$?
  case "$status:$output" in
    0:absent) return 0 ;;
    1:present) fail "$category is visible at ${path%/*} outside its owning fixture" ;;
    124:*|125:*|137:*) fail "$category absence could not be checked because docker exec failed" ;;
    *) fail "$category absence could not be verified outside its owning fixture" ;;
  esac
}

write_owned_marker() {
  local name="$1"
  local category="$2"
  local path="$3"
  docker_exec "$name" sh -c 'umask 077; printf "%s\n" "$2" > "$1"' \
    sh "$path" "synthetic-write-$run_id" >/dev/null 2>&1 \
    || fail "$category is not writable at ${path%/*} in its owning fixture"
}

measure_canary() {
  local name="$1"
  local category="$2"
  local path="$3"
  local measurement=""
  measurement="$(docker_exec "$name" sh -c '
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

assert_antigravity_missing_runtime_rejection() {
  local output=""
  local status=0
  output="$(docker_exec "$antigravity_name" run-antigravity 2>&1)" || status=$?
  if (( status == 0 )); then
    fail "missing synthetic Antigravity runtime unexpectedly launched"
  fi
  if (( status == 124 || status == 125 || status == 126 || status == 127 || status == 137 )); then
    fail "Antigravity rejection command could not execute"
  fi
  (( status == 1 )) || fail "missing synthetic Antigravity runtime returned an unexpected status"
  grep -Fq -- 'ERROR: Antigravity is absent, damaged or incomplete at the canonical path:' <<<"$output" \
    || fail "Antigravity rejection did not report the expected admission state"
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
  docker_exec "$name" tmux -L "$socket" new-session -d -s "$session" 'sleep 300' >/dev/null 2>&1 \
    || fail "$role fixture could not create its tmux socket"
  docker_exec "$name" test -S "/tmp/tmux-0/$socket" >/dev/null 2>&1 \
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
printf 'capability-probe\n' >"$test_root/codex/workspace/.hardening-capability-probe"
printf 'capability-probe\n' >"$test_root/antigravity/workspace/.hardening-capability-probe"
chmod 0711 -- "$test_root/antigravity/workspace"
install -d -m 0700 -- \
  "$test_root/launcher/password" \
  "$test_root/codex/password" \
  "$test_root/antigravity/password"
launcher_password="synthetic-launcher-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
launcher_password_source="$test_root/launcher/password/web_password"
codex_password_marker="$(marker_name codex-password)"
antigravity_password_marker="$(marker_name antigravity-password)"
codex_password_source="$test_root/codex/password/$codex_password_marker"
antigravity_password_source="$test_root/antigravity/password/$antigravity_password_marker"
printf '%s\n' "$launcher_password" >"$launcher_password_source"
printf 'synthetic-terminal-password-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$codex_password_source"
printf 'synthetic-terminal-password-%s\n' "$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')" >"$antigravity_password_source"
chmod 0600 -- "$launcher_password_source" "$codex_password_source" "$antigravity_password_source"
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
    --read-only \
    --cap-drop ALL \
    --cap-add DAC_READ_SEARCH \
    --cap-add SETGID \
    --cap-add SETUID \
    --pids-limit 64 \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
    --tmpfs /run:rw,nosuid,nodev,size=16m,mode=755 \
    --env REMOTE_DEV_ROLE=launcher \
    --env REMOTE_DEV_START_MODE=menu \
    --env WEB_USERNAME=isolation-launcher \
    --env WEB_PASSWORD_FILE=/run/secrets/launcher_password \
    --env WEB_CHECK_ORIGIN=1 \
    --env WEB_PORT=7680 \
    --mount "type=bind,src=$launcher_password_source,dst=/run/secrets/launcher_password,readonly" \
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
    --network none \
    --read-only \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --cap-add KILL \
    --cap-add SETGID \
    --cap-add SETUID \
    --pids-limit 1024 \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777 \
    --tmpfs /run:rw,nosuid,nodev,size=1536m,mode=755 \
    --env REMOTE_DEV_ROLE=codex \
    --env WORKSPACE=/workspace \
    --env CODEX_HOME=/root/.codex \
    --env REMOTE_DEV_CODEX_RUNTIME_ROOT=/root/.local/share/remote-dev/codex-runtime \
    --env GH_CONFIG_DIR=/root/.config/gh \
    --env GIT_CONFIG_GLOBAL=/root/.config/git/config \
    --env WEB_PASSWORD_FILE=/run/secrets/web_password \
    --env WEB_PORT=7681 \
    --env NPM_CONFIG_CACHE=/tmp/remote-dev-npm-cache \
    --env UV_CACHE_DIR=/tmp/remote-dev-uv-cache \
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
    --network none \
    --read-only \
    --cap-drop ALL \
    --cap-add CHOWN \
    --cap-add DAC_OVERRIDE \
    --cap-add FOWNER \
    --cap-add KILL \
    --cap-add SETGID \
    --cap-add SETUID \
    --pids-limit 1024 \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777 \
    --tmpfs /run:rw,nosuid,nodev,size=64m,mode=755 \
    --env REMOTE_DEV_ROLE=antigravity \
    --env REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
    --env AGY_CLI_DISABLE_AUTO_UPDATE=true \
    --env WORKSPACE=/workspace \
    --env GH_CONFIG_DIR=/root/.config/gh \
    --env GIT_CONFIG_GLOBAL=/root/.config/git/config \
    --env WEB_PASSWORD_FILE=/run/secrets/web_password \
    --env WEB_PORT=7682 \
    --env NPM_CONFIG_CACHE=/tmp/remote-dev-npm-cache \
    --env UV_CACHE_DIR=/tmp/remote-dev-uv-cache \
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
assert_hardening_contract "$launcher_name" launcher
assert_hardening_contract "$codex_name" codex
assert_hardening_contract "$antigravity_name" antigravity
assert_runtime_mount_options "$launcher_name" launcher
assert_runtime_mount_options "$codex_name" codex
assert_runtime_mount_options "$antigravity_name" antigravity
assert_launcher_runtime_identity
assert_agent_runtime_identity "$codex_name" Codex
assert_agent_runtime_identity "$antigravity_name" Antigravity
assert_launcher_http_security
assert_read_only_rootfs "$launcher_name" launcher
assert_read_only_rootfs "$codex_name" Codex
assert_read_only_rootfs "$antigravity_name" Antigravity
assert_distinct_agent_sources
assert_terminal_password_canary "$codex_name" Codex "$codex_password_measurement"
assert_terminal_password_canary "$antigravity_name" Antigravity "$antigravity_password_measurement"
assert_codex_toolchain_workflow
assert_hardened_antigravity_host_fixtures

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

assert_antigravity_missing_runtime_rejection
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
assert_hardening_contract "$codex_name" codex
assert_runtime_mount_options "$codex_name" codex
assert_agent_runtime_identity "$codex_name" Codex
assert_read_only_rootfs "$codex_name" Codex
assert_distinct_agent_sources
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
assert_hardening_contract "$antigravity_name" antigravity
assert_runtime_mount_options "$antigravity_name" antigravity
assert_agent_runtime_identity "$antigravity_name" Antigravity
assert_read_only_rootfs "$antigravity_name" Antigravity
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

echo "Hardened cross-service isolation and offline toolchain canaries: OK"
