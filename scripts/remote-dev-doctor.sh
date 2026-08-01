#!/usr/bin/env bash
set -uo pipefail

runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
source "$runtime_lib"

role="$(remote_dev_resolve_role)" || exit $?
export REMOTE_DEV_ROLE="$role"

status=0
check_cmd() {
  local cmd="$1"
  printf '%-24s ' "$cmd"
  if command -v "$cmd" >/dev/null 2>&1; then
    command -v "$cmd"
  else
    echo "MISSING"
    status=1
  fi
}

cat <<EOF_HEADER
Remote Dev diagnostics
======================
Role: $role
User: $(id)
Home: ${HOME:-unset}
Workspace: ${WORKSPACE:-unset}
GitHub config: ${GH_CONFIG_DIR:-unset}
EOF_HEADER

if [[ "$role" == codex ]]; then
  echo "Codex home: ${CODEX_HOME:-unset}"
fi

echo
common_commands=(
  start-remote-dev-web
  attach-remote-dev-tmux
  remote-dev-menu
  remote-dev-doctor
  remote-dev-version
  gh git python node npm uv mise ttyd tmux ssh rg fd
)
for cmd in "${common_commands[@]}"; do
  check_cmd "$cmd"
done
if [[ "$role" == codex ]]; then
  check_cmd codex
  check_cmd run-codex
fi

echo
if remote-dev-version --check; then
  remote-dev-version
else
  echo 'Image metadata: unavailable or invalid'
  remote-dev-version 2>/dev/null || true
  status=1
fi
gh --version 2>/dev/null | head -n 1 || true
python --version 2>/dev/null || true
node --version 2>/dev/null || true
uv --version 2>/dev/null || true

if [[ "$role" == codex ]]; then
  echo
  if policy_output="$(run-codex --print-policy 2>/dev/null)"; then
    printf '%s\n' "$policy_output"
  else
    echo 'Codex launch policy: unavailable'
    status=1
  fi
  if command -v bwrap >/dev/null 2>&1; then
    echo 'WARNING: system Bubblewrap is unexpectedly installed; the supported launcher still disables the inner sandbox.'
    status=1
  fi
  echo 'INFO: danger-full-access disables only the unsupported inner sandbox; the outer container remains the supported isolation boundary.'
  echo 'INFO: approval prompts are not a sandbox or an isolation boundary.'
  echo 'INFO: do not add privileged mode, SYS_ADMIN or unconfined security profiles to enable a nested sandbox.'

  printf 'Codex auth: '
  if codex login status >/dev/null 2>&1; then
    echo OK
  else
    echo 'not authenticated or unavailable'
  fi
fi

printf 'GitHub auth: '
if gh auth status >/dev/null 2>&1; then
  echo OK
else
  echo 'not authenticated'
fi

writable_paths=(
  "${WORKSPACE:-/workspace}"
  "${GH_CONFIG_DIR:-/root/.config/gh}"
)
if [[ "$role" == codex ]]; then
  writable_paths+=("${CODEX_HOME:-/root/.codex}")
fi
for path in "${writable_paths[@]}"; do
  printf 'Writable %-38s ' "$path"
  if [[ -d "$path" && -w "$path" ]]; then
    echo OK
  else
    echo NO
    status=1
  fi
done

if [[ -S /var/run/docker.sock ]]; then
  echo 'WARNING: /var/run/docker.sock is mounted. This is not supported.'
  status=1
fi
if [[ -e /host ]]; then
  echo 'WARNING: /host exists. Check that the NAS root filesystem is not mounted.'
fi

if [[ "$role" == codex && -f "${CODEX_HOME:-/root/.codex}/auth.json" ]]; then
  mode="$(stat -c '%a' "${CODEX_HOME:-/root/.codex}/auth.json" 2>/dev/null || true)"
  echo "Codex auth.json permissions: ${mode:-unknown}"
  if [[ "$mode" != 600 && "$mode" != 400 ]]; then
    echo 'WARNING: auth.json should normally be readable only by root.'
    status=1
  fi
fi

exit "$status"
