#!/usr/bin/env bash
set -uo pipefail

status=0
check_cmd() {
  local cmd="$1"
  printf '%-18s ' "$cmd"
  if command -v "$cmd" >/dev/null 2>&1; then
    command -v "$cmd"
  else
    echo "MISSING"
    status=1
  fi
}

cat <<EOF_HEADER
Codex Remote Dev diagnostics
============================
User: $(id)
Home: ${HOME:-unset}
Workspace: ${WORKSPACE:-unset}
Codex home: ${CODEX_HOME:-unset}
GitHub config: ${GH_CONFIG_DIR:-unset}
EOF_HEADER

echo
for cmd in codex gh git python node npm uv mise ttyd tmux ssh rg fd remote-dev-version; do
  check_cmd "$cmd"
done

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

echo
if command -v bwrap >/dev/null 2>&1; then
  if bwrap --ro-bind / / /bin/true >/dev/null 2>&1; then
    echo 'Inner sandbox: Bubblewrap operational'
  else
    echo 'Inner sandbox: unavailable (Bubblewrap cannot create its namespace)'
  fi
else
  echo 'Inner sandbox: unavailable / not installed'
fi
echo 'Isolation boundary: outer container'
echo 'Approval policy: explicit approval required when Codex cannot sandbox a command'
echo 'INFO: do not add privileged mode, SYS_ADMIN or unconfined security profiles to enable a nested sandbox.'

printf 'Codex auth: '
if codex login status >/dev/null 2>&1; then
  echo OK
else
  echo 'not authenticated or unavailable'
fi

printf 'GitHub auth: '
if gh auth status >/dev/null 2>&1; then
  echo OK
else
  echo 'not authenticated'
fi

for path in "${WORKSPACE:-/workspace}" "${CODEX_HOME:-/root/.codex}" "${GH_CONFIG_DIR:-/root/.config/gh}"; do
  printf 'Writable %-32s ' "$path"
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

if [[ -f "${CODEX_HOME:-/root/.codex}/auth.json" ]]; then
  mode="$(stat -c '%a' "${CODEX_HOME:-/root/.codex}/auth.json" 2>/dev/null || true)"
  echo "Codex auth.json permissions: ${mode:-unknown}"
  if [[ "$mode" != 600 && "$mode" != 400 ]]; then
    echo 'WARNING: auth.json should normally be readable only by root.'
    status=1
  fi
fi

exit "$status"
