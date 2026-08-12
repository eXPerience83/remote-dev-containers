#!/usr/bin/env bash
set -euo pipefail

if (( $# != 0 && $# != 2 )); then
  echo "Usage: codex-smoke-test [expected-image-version expected-source-revision]" >&2
  exit 2
fi

if [[ ! -r /etc/os-release ]]; then
  echo "MISSING: /etc/os-release" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
expected_ubuntu="${REMOTE_DEV_UBUNTU_VERSION:-}"
printf 'Base OS: %s %s (expected Ubuntu %s)\n' "${ID:-unknown}" "${VERSION_ID:-unknown}" "${expected_ubuntu:-unset}"
if [[ "${ID:-}" != "ubuntu" || -z "$expected_ubuntu" || "${VERSION_ID:-}" != "$expected_ubuntu" ]]; then
  echo "ERROR: child image is not based on the expected Ubuntu release" >&2
  exit 1
fi

lib_dir=/usr/local/lib/remote-dev
# shellcheck source=/usr/local/lib/remote-dev/format-short-revision.sh
source "$lib_dir/format-short-revision.sh"

workdir="$(mktemp -d)"
tmux_socket="remote-dev-smoke-$$"
direct_codex_socket="${tmux_socket}-direct-codex"
direct_shell_socket="${tmux_socket}-direct-shell"

cleanup() {
  local socket=""
  for socket in "$tmux_socket" "$direct_codex_socket" "$direct_shell_socket"; do
    tmux -L "$socket" kill-server >/dev/null 2>&1 || true
  done
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

assert_short_revision() {
  local input="$1"
  local expected="$2"
  local actual=""

  actual="$(format_short_revision "$input")"
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: revision formatting mismatch for $input: expected $expected, got $actual" >&2
    exit 1
  fi
}

wait_for_tmux_session_exit() {
  local socket="$1"
  local session="$2"
  local attempt=""

  for attempt in $(seq 1 50); do
    if ! tmux -L "$socket" has-session -t "=$session" 2>/dev/null; then
      return 0
    fi
    sleep 0.1
  done

  echo "ERROR: tmux session $session did not exit after its direct command completed" >&2
  tmux -L "$socket" capture-pane -p -t "=$session:" >&2 || true
  exit 1
}

assert_auth_hardened() {
  local label="$1"
  local codex_home="$2"
  local auth_file="$codex_home/auth.json"
  local mode=""

  if [[ ! -f "$auth_file" ]]; then
    echo "ERROR: $label did not create $auth_file" >&2
    exit 1
  fi

  mode="$(stat -c '%a' "$auth_file")"
  if [[ "$mode" != 600 ]]; then
    echo "ERROR: $label left auth.json with mode $mode, expected 600" >&2
    exit 1
  fi
}

escape_sed_replacement() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//&/\\&}"
  value="${value//|/\\|}"
  printf '%s' "$value"
}

sample_revision=0123456789abcdef0123456789abcdef01234567
assert_short_revision "$sample_revision" 0123456789ab
assert_short_revision "${sample_revision}-dirty" 0123456789ab-dirty
assert_short_revision 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef 0123456789ab
assert_short_revision local-untracked local-untracked
assert_short_revision release-marker release-marker
echo "Source revision formatting cases: OK"

metadata_dir=/usr/share/remote-dev
if ! remote-dev-version --check; then
  echo "ERROR: embedded image metadata is missing or invalid" >&2
  exit 1
fi

image_version="$(<"$metadata_dir/image-version")"
source_revision="$(<"$metadata_dir/source-revision")"
expected_image_version="${1:-$image_version}"
expected_source_revision="${2:-$source_revision}"
codex_version="$(/usr/local/bin/codex --version)"
launcher_version="$(/usr/local/bin/run-codex --version)"

if [[ "$launcher_version" != "$codex_version" ]]; then
  echo "ERROR: run-codex did not execute the pinned Codex binary with its fixed policy" >&2
  printf 'Raw Codex: %s\nLauncher: %s\n' "$codex_version" "$launcher_version" >&2
  exit 1
fi

if [[ "$image_version" != "$expected_image_version" ]]; then
  echo "ERROR: image version metadata mismatch: expected $expected_image_version, got $image_version" >&2
  exit 1
fi
if [[ "$source_revision" != "$expected_source_revision" ]]; then
  echo "ERROR: source revision metadata mismatch: expected $expected_source_revision, got $source_revision" >&2
  exit 1
fi

default_output="$(remote-dev-version)"
menu_output="$(remote-dev-version --menu)"
short_revision="$(format_short_revision "$source_revision")"

for expected_line in \
  "Image version: $image_version" \
  "Source revision: $source_revision" \
  "Codex CLI: $codex_version"; do
  if ! grep -Fxq "$expected_line" <<<"$default_output"; then
    echo "ERROR: remote-dev-version output is missing: $expected_line" >&2
    exit 1
  fi
done
for expected_line in \
  "Image: $image_version @ $short_revision" \
  "Codex: $codex_version"; do
  if ! grep -Fxq "$expected_line" <<<"$menu_output"; then
    echo "ERROR: menu version output is missing: $expected_line" >&2
    exit 1
  fi
done

spoof_metadata_dir="$workdir/spoof-metadata"
mkdir -p "$spoof_metadata_dir"
printf 'spoofed\n' > "$spoof_metadata_dir/image-version"
printf 'spoofed-revision\n' > "$spoof_metadata_dir/source-revision"
spoofed_output="$(
  REMOTE_DEV_METADATA_DIR="$spoof_metadata_dir" \
  REMOTE_DEV_LIB_DIR="$workdir/missing-library" \
    remote-dev-version --menu
)"
if [[ "$spoofed_output" != "$menu_output" ]]; then
  echo "ERROR: runtime environment variables must not replace image build identity" >&2
  exit 1
fi

printf '%s\n' "$default_output"
printf '%s\n' "$menu_output"
echo "Image identity is bound to embedded metadata: OK"
printf '%s\n' "$codex_version"
echo "Pinned Codex launcher compatibility: OK"

if command -v bwrap >/dev/null 2>&1; then
  echo "ERROR: the system Bubblewrap executable must not be installed in the default outer-isolation image" >&2
  exit 1
fi
echo "System Bubblewrap executable is absent: OK"
gh --version | head -n 1
git --version
python --version
node --version
npm --version
uv --version
ttyd --version
tmux -V
mise --version

cd "$workdir"
git init -q
printf 'print("ok")\n' > smoke.py
python smoke.py | grep -Fx ok
node -e 'console.log("ok")' | grep -Fx ok

wrapper_state="$workdir/direct-wrapper-state"
mkdir -p "$wrapper_state"
wrapper_status=0
CODEX_HOME="$wrapper_state" \
  /usr/local/bin/run-direct-session \
  bash -c 'umask 000; printf "token\n" > "$CODEX_HOME/auth.json"; chmod 0660 "$CODEX_HOME/auth.json"; exit 23' \
  || wrapper_status=$?
if (( wrapper_status != 23 )); then
  echo "ERROR: direct-session wrapper returned $wrapper_status, expected the command status 23" >&2
  exit 1
fi
assert_auth_hardened "Direct-session wrapper" "$wrapper_state"
echo "Direct-session wrapper preserves status and hardens state: OK"

if [[ "${REMOTE_DEV_SKIP_TMUX_SMOKE:-0}" != "1" ]]; then
  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=fresh-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux

  fresh_name="$(tmux -L "$tmux_socket" display-message -p -t '=fresh-session:' '#{window_name}')"
  if [[ "$fresh_name" != remote-dev ]]; then
    echo "ERROR: fresh tmux session window name is $fresh_name, expected remote-dev" >&2
    exit 1
  fi

  tmux -L "$tmux_socket" new-session -d -s existing-session -n legacy-name 'sleep 30'
  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=existing-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux

  existing_name="$(tmux -L "$tmux_socket" display-message -p -t '=existing-session:' '#{window_name}')"
  if [[ "$existing_name" != remote-dev ]]; then
    echo "ERROR: existing tmux session window name is $existing_name, expected remote-dev" >&2
    exit 1
  fi

  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=concurrent-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux &
  first_attach_pid=$!

  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=concurrent-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux &
  second_attach_pid=$!

  first_attach_status=0
  second_attach_status=0
  wait "$first_attach_pid" || first_attach_status=$?
  wait "$second_attach_pid" || second_attach_status=$?
  if (( first_attach_status != 0 || second_attach_status != 0 )); then
    echo "ERROR: concurrent tmux attach failed with statuses $first_attach_status and $second_attach_status" >&2
    exit 1
  fi

  concurrent_name="$(tmux -L "$tmux_socket" display-message -p -t '=concurrent-session:' '#{window_name}')"
  if [[ "$concurrent_name" != remote-dev ]]; then
    echo "ERROR: concurrent tmux session window name is $concurrent_name, expected remote-dev" >&2
    exit 1
  fi

  direct_codex_state="$workdir/direct-codex-state"
  direct_codex_workspace="$workdir/direct-codex-workspace"
  direct_codex_project="$direct_codex_workspace/project"
  direct_codex_args="$workdir/direct-codex-args"
  direct_codex_cwd="$workdir/direct-codex-cwd"
  fake_codex="$workdir/fake codex&pipe|back\\slash"
  test_run_codex="$workdir/run codex&pipe|back\\slash"
  test_attach_tmux="$workdir/attach remote-dev tmux"
  mkdir -p "$direct_codex_state" "$direct_codex_project"
  cat > "$fake_codex" <<'FAKE_CODEX'
#!/usr/bin/env bash
set -euo pipefail
pwd > "$REMOTE_DEV_TEST_DIRECT_CODEX_CWD"
printf '%s\n' "$@" > "$REMOTE_DEV_TEST_DIRECT_CODEX_ARGS"
umask 000
printf 'token\n' > "$CODEX_HOME/auth.json"
chmod 0660 "$CODEX_HOME/auth.json"
sleep 1
FAKE_CODEX
  chmod 0755 "$fake_codex"

  if ! grep -Fxq 'readonly codex_binary=/usr/local/bin/codex' /usr/local/bin/run-codex; then
    echo "ERROR: installed run-codex does not pin /usr/local/bin/codex" >&2
    exit 1
  fi
  if ! grep -Fxq 'readonly run_codex_binary=/usr/local/bin/run-codex' /usr/local/bin/attach-remote-dev-tmux; then
    echo "ERROR: installed tmux launcher does not pin /usr/local/bin/run-codex" >&2
    exit 1
  fi
  if ! grep -Fq 'printf -v quoted_run_codex_binary' /usr/local/bin/attach-remote-dev-tmux; then
    echo "ERROR: START_MODE=codex does not shell-quote the pinned run-codex path" >&2
    exit 1
  fi
  if ! grep -Fq 'remote_dev_resolve_project "$workspace"' /usr/local/bin/attach-remote-dev-tmux; then
    echo "ERROR: direct agent mode does not resolve a bounded project below WORKSPACE" >&2
    exit 1
  fi

  printf -v fake_codex_quoted '%q' "$fake_codex"
  printf -v test_run_codex_quoted '%q' "$test_run_codex"
  fake_codex_replacement="$(escape_sed_replacement "$fake_codex_quoted")"
  test_run_codex_replacement="$(escape_sed_replacement "$test_run_codex_quoted")"

  sed \
    "s|^readonly codex_binary=/usr/local/bin/codex$|readonly codex_binary=$fake_codex_replacement|" \
    /usr/local/bin/run-codex > "$test_run_codex"
  sed \
    "s|^readonly run_codex_binary=/usr/local/bin/run-codex$|readonly run_codex_binary=$test_run_codex_replacement|" \
    /usr/local/bin/attach-remote-dev-tmux > "$test_attach_tmux"
  chmod 0755 "$test_run_codex" "$test_attach_tmux"

  if ! grep -Fxq "readonly codex_binary=$fake_codex_quoted" "$test_run_codex"; then
    echo "ERROR: failed to create an isolated run-codex smoke launcher" >&2
    exit 1
  fi
  if ! grep -Fxq "readonly run_codex_binary=$test_run_codex_quoted" "$test_attach_tmux"; then
    echo "ERROR: failed to route the isolated tmux smoke launcher" >&2
    exit 1
  fi

  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$direct_codex_socket" \
  TMUX_SESSION=direct-codex \
  START_MODE=codex \
  REMOTE_DEV_PROJECT=project \
  WORKSPACE="$direct_codex_workspace" \
  CODEX_HOME="$direct_codex_state" \
  REMOTE_DEV_TEST_DIRECT_CODEX_ARGS="$direct_codex_args" \
  REMOTE_DEV_TEST_DIRECT_CODEX_CWD="$direct_codex_cwd" \
    "$test_attach_tmux"

  wait_for_tmux_session_exit "$direct_codex_socket" direct-codex
  assert_auth_hardened "START_MODE=codex" "$direct_codex_state"
  if [[ "$(<"$direct_codex_cwd")" != "$direct_codex_project" ]]; then
    echo "ERROR: START_MODE=codex did not run from the selected project" >&2
    exit 1
  fi
  mapfile -t direct_codex_argv < "$direct_codex_args"
  direct_cd_seen=0
  for ((index = 0; index + 1 < ${#direct_codex_argv[@]}; index++)); do
    if [[ "${direct_codex_argv[$index]}" == --cd \
       && "${direct_codex_argv[$((index + 1))]}" == "$direct_codex_project" ]]; then
      direct_cd_seen=1
      break
    fi
  done
  if (( direct_cd_seen != 1 )); then
    echo "ERROR: START_MODE=codex did not pass --cd with the selected project" >&2
    printf 'Arguments: %s\n' "${direct_codex_argv[*]}" >&2
    exit 1
  fi

  direct_shell_state="$workdir/direct-shell-state"
  mkdir -p "$direct_shell_state"
  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$direct_shell_socket" \
  TMUX_SESSION=direct-shell \
  START_MODE=shell \
  WORKSPACE=/workspace \
  CODEX_HOME="$direct_shell_state" \
    /usr/local/bin/attach-remote-dev-tmux

  tmux -L "$direct_shell_socket" send-keys -t '=direct-shell:' \
    'umask 000; printf "token\n" > "$CODEX_HOME/auth.json"; chmod 0660 "$CODEX_HOME/auth.json"; exit' C-m
  wait_for_tmux_session_exit "$direct_shell_socket" direct-shell
  assert_auth_hardened "START_MODE=shell" "$direct_shell_state"

  echo "Tmux fresh, existing and concurrent session paths: OK"
  echo "Direct project-scoped Codex and shell start modes harden state after exit: OK"
else
  echo "Tmux runtime smoke test: skipped during image build"
fi
