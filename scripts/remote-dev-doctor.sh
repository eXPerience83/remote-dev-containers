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
  printf '%-32s ' "$cmd"
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
EOF_HEADER

if [[ "$role" == launcher ]]; then
  cat <<EOF_LAUNCHER
Web bind: ${WEB_BIND:-0.0.0.0}
Web port: ${WEB_PORT:-7680}
Web base path: ${WEB_BASE_PATH:-/}
Codex route host: ${REMOTE_DEV_LAUNCHER_CODEX_HOST:-browser hostname}
Codex route port: ${REMOTE_DEV_LAUNCHER_CODEX_PORT:-7681}
Codex route scheme: ${REMOTE_DEV_LAUNCHER_CODEX_SCHEME:-browser scheme}
Codex route path: ${REMOTE_DEV_LAUNCHER_CODEX_PATH:-/}
Antigravity route enabled: ${REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED:-0}
Antigravity route host: ${REMOTE_DEV_LAUNCHER_ANTIGRAVITY_HOST:-browser hostname}
Antigravity route port: ${REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PORT:-7682}
Antigravity route scheme: ${REMOTE_DEV_LAUNCHER_ANTIGRAVITY_SCHEME:-browser scheme}
Antigravity route path: ${REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PATH:-/}
Available roles: launcher, codex, shell
Experimental gated role: antigravity (requires REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1)
EOF_LAUNCHER
else
  cat <<EOF_AGENT
Workspace: ${WORKSPACE:-unset}
GitHub config: ${GH_CONFIG_DIR:-unset}
EOF_AGENT
  if [[ "$role" == codex ]]; then
    echo "Codex home: ${CODEX_HOME:-unset}"
    echo "Codex runtime state: ${REMOTE_DEV_CODEX_RUNTIME_ROOT:-/root/.local/share/remote-dev/codex-runtime}"
    echo "Context7 private state: ${CODEX_HOME:-/root/.codex}/.remote-dev-context7"
  elif [[ "$role" == antigravity ]]; then
    readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh
    if [[ -r "$paths_lib" && ! -L "$paths_lib" ]]; then
      # shellcheck source=/usr/local/lib/remote-dev/antigravity-paths.sh
      source "$paths_lib"
      echo "Antigravity executable: $ANTIGRAVITY_BINARY"
      echo "Antigravity local state: $ANTIGRAVITY_STATE_DIR"
      echo "Antigravity vendor state: $ANTIGRAVITY_VENDOR_STATE_DIR"
      echo "Antigravity project config: $ANTIGRAVITY_CONFIG_STATE_DIR"
    else
      echo "Antigravity path definitions: MISSING"
      status=1
    fi
  fi
fi

echo
if [[ "$role" == launcher ]]; then
  common_commands=(
    start-remote-dev-web
    remote-dev-launcher
    remote-dev-healthcheck
    remote-dev-doctor
    remote-dev-version
    python curl
  )
else
  common_commands=(
    start-remote-dev-web
    attach-remote-dev-tmux
    remote-dev-menu
    remote-dev-healthcheck
    remote-dev-doctor
    remote-dev-version
    gh git python node npm uv mise ttyd tmux ssh rg fd
  )
fi
for cmd in "${common_commands[@]}"; do
  check_cmd "$cmd"
done
if [[ "$role" == codex ]]; then
  check_cmd codex
  check_cmd run-codex
  check_cmd /usr/local/bin/remote-dev-codex-runtime
  check_cmd /usr/local/bin/remote-dev-context7
elif [[ "$role" == antigravity ]]; then
  check_cmd remote-dev-antigravity
  check_cmd remote-dev-install-antigravity
  check_cmd remote-dev-update-antigravity
  check_cmd run-antigravity
fi

echo
if remote-dev-version --check; then
  remote-dev-version
else
  echo 'Image metadata: unavailable or invalid'
  remote-dev-version 2>/dev/null || true
  status=1
fi

if [[ "$role" == launcher ]]; then
  echo 'Launcher state boundary: no agent workspace or credential mounts are required.'
else
  gh --version 2>/dev/null | head -n 1 || true
  python --version 2>/dev/null || true
  node --version 2>/dev/null || true
  uv --version 2>/dev/null || true
fi

if [[ "$role" == codex ]]; then
  echo
  codex_runtime_verify=0
  codex_runtime_verify_command=(timeout --signal=TERM --kill-after=5s 60s /usr/local/bin/remote-dev-codex-runtime verify)
  if "${codex_runtime_verify_command[@]}"; then
    :
  else
    codex_runtime_verify=$?
    echo "Codex runtime full integrity: unavailable (exit $codex_runtime_verify)"
    status=1
  fi
  codex_runtime_status=0
  codex_runtime_status_command=(/usr/local/bin/remote-dev-codex-runtime status)
  if "${codex_runtime_status_command[@]}"; then
    :
  else
    codex_runtime_status=$?
    echo "Codex runtime status: unavailable (exit $codex_runtime_status)"
    status=1
  fi
  echo 'Codex runtime trust boundary: official package may be newer than the image; review-pending means Remote Dev has not reviewed that exact release.'
  echo 'Codex runtime automatic updates: disabled; network access occurs only after the explicit update action.'
  echo 'Codex runtime fallback: missing, damaged, modified, equal or older runtime state selects the immutable bundled CLI.'

  echo
  context7_status_code=0
  context7_status_command=(/usr/local/bin/remote-dev-context7 status --menu)
  context7_status="$("${context7_status_command[@]}" 2>&1)" || context7_status_code=$?
  if [[ -n "$context7_status" ]]; then
    printf '%s\n' "$context7_status"
  else
    echo "Context7: status unavailable (exit $context7_status_code)"
  fi
  if (( context7_status_code != 0 )); then
    status=1
  fi
  echo 'Context7 boundary: optional external Upstash hosted MCP service; no Context7 runtime is bundled or downloaded.'
  echo 'Context7 passive diagnostics network: not used; only explicit test and enabled Codex MCP use may contact Context7.'
  echo 'Remote Dev-managed Context7 credentials are stored only in Codex-private state; Remote Dev diagnostics never print credentials.'

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
elif [[ "$role" == antigravity ]]; then
  echo
  antigravity_verify_code=0
  antigravity_verify_command=(timeout --signal=TERM --kill-after=5s 60s remote-dev-antigravity verify)
  if "${antigravity_verify_command[@]}"; then
    :
  else
    antigravity_verify_code=$?
    echo "Antigravity runtime full integrity: unavailable (exit $antigravity_verify_code)"
    status=1
  fi
  antigravity_status_code=0
  antigravity_status="$(remote-dev-antigravity status --menu 2>&1)" || antigravity_status_code=$?
  echo "$antigravity_status"
  if (( antigravity_status_code != 0 && antigravity_status_code != 3 )); then
    status=1
  fi
  echo 'Antigravity support status: experimental validation only; not yet a supported integration.'
  echo 'Antigravity trust boundary: runtime-installed from Google; not bundled in the image or build-time SBOM.'
  echo 'Antigravity automatic CLI updates: disabled by the Remote Dev launcher.'
  echo 'Antigravity authentication: managed only by the official Google client.'
fi

if [[ "$role" != launcher ]]; then
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
    writable_paths+=(
      "${CODEX_HOME:-/root/.codex}"
      "${REMOTE_DEV_CODEX_RUNTIME_ROOT:-/root/.local/share/remote-dev/codex-runtime}"
    )
  elif [[ "$role" == antigravity ]]; then
    writable_paths+=(
      "$ANTIGRAVITY_BIN_DIR"
      "$ANTIGRAVITY_STATE_DIR"
      "$ANTIGRAVITY_VENDOR_STATE_DIR"
      "$ANTIGRAVITY_CONFIG_STATE_DIR"
    )
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
fi

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
elif [[ "$role" == antigravity && -n "${ANTIGRAVITY_BINARY:-}" && -f "$ANTIGRAVITY_BINARY" ]]; then
  mode="$(stat -c '%a' "$ANTIGRAVITY_BINARY" 2>/dev/null || true)"
  echo "Antigravity executable permissions: ${mode:-unknown}"
  if [[ "$mode" != 700 ]]; then
    echo 'WARNING: the runtime-installed Antigravity executable should be accessible only by root.'
    status=1
  fi
fi

exit "$status"
