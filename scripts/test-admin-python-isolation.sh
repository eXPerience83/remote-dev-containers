#!/usr/bin/env bash
set -euo pipefail

# Run inside an existing hardened role fixture. The host feeds this script over
# stdin; no extra production mount, dependency or toolchain download is needed.
: "${TMPDIR:?}"
[[ "$REMOTE_DEV_ROLE" == codex || "$REMOTE_DEV_ROLE" == antigravity ]]
readonly admin_python=/usr/local/lib/remote-dev/python
scratch="$(mktemp -d "$TMPDIR/admin-python-XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir -p "$scratch"/{neutral,unsafe,selected,missing,state,cache,config,store/installs/python,fake}
export MISE_STATE_DIR="$scratch/state" MISE_CACHE_DIR="$scratch/cache"
export MISE_CONFIG_DIR="$scratch/config" MISE_GLOBAL_CONFIG_FILE="$scratch/config/config.toml"
unset MISE_TRUSTED_CONFIG_PATHS MISE_TRUSTED_CONFIG_FILES
export PATH="/opt/remote-dev/mise/shims:$scratch/fake:/usr/local/bin:/usr/bin:/bin"
cd "$scratch/neutral"
image_identity="$("$admin_python" -I -c 'import sys; print(sys.version); print(sys.prefix)')"
[[ "$(realpath "$admin_python")" == /opt/remote-dev/mise/installs/python/*/bin/* ]]
[[ "$(stat -c '%u:%g %a' /usr/local/lib/remote-dev)" == '0:0 755' ]]
for program in remote-dev-agent-guidance remote-dev-codex-runtime \
  remote-dev-prepare-development-scratch validate-codex-project-boundary \
  remote-dev-context7-device-login remote-dev-antigravity-oauth \
  remote-dev-antigravity-picker remote-dev-antigravity-policy remote-dev-launcher; do
  [[ "$(head -n 1 "/usr/local/bin/$program")" == "#!$admin_python -I" ]]
done

snapshot() {
  "$admin_python" -I - "$@" <<'PY'
from pathlib import Path
import hashlib
import os
import stat
import sys
for arg in sys.argv[1:]:
    root = Path(arg)
    for path in sorted([root, *root.rglob('*')]):
        try:
            s = path.lstat()
        except FileNotFoundError:
            continue
        value = os.readlink(path) if stat.S_ISLNK(s.st_mode) else (
            hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(s.st_mode) else '')
        print(path, s.st_mode, s.st_uid, s.st_gid, s.st_size, s.st_mtime_ns, s.st_ctime_ns, value)
PY
}

# Project commands must fail closed; a same-name PATH fallback would leave proof.
for cmd in python python3; do
  # Expanded only by the synthetic fallback child.
  # shellcheck disable=SC2016
  printf '%s\n' '#!/bin/bash' 'touch "$MISE_STATE_DIR/fallback"; exit 0' > "$scratch/fake/$cmd"
  chmod 0700 "$scratch/fake/$cmd"
done
cat > "$scratch/unsafe/mise.toml" <<EOF
[env]
PROBE = "{{ exec(command='touch $scratch/executed-project') }}"
EOF
printf '[tools]\npython = "3.12.1"\n' > "$scratch/missing/mise.toml"
[[ ! -e /opt/remote-dev/mise/installs/python/3.12.1 ]]

# An offline installed-version fixture in a private test store. This is a real
# executable venv with a distinct prefix, registered under a synthetic version;
# it is not a second bundled release or a supported writable toolchain store.
"$admin_python" -I -m venv --without-pip "$scratch/store/installs/python/3.14.999"
printf '[tools]\npython = "3.14.999"\n' > "$scratch/selected/mise.toml"

snapshot /opt/remote-dev/mise /usr/local/lib/remote-dev/python > "$scratch/image-before"
snapshot "$scratch/unsafe" "$scratch/missing" "$scratch/selected" "$scratch/store" > "$scratch/projects-before"

probe_control_plane() {
  local project="$1" command index=0
  local -a commands=(guidance status verify doctor context7 antigravity)
  cd "$scratch/$project"
  snapshot "$MISE_STATE_DIR" /root/.local/state/mise > "$scratch/state-before"
  for command in "${commands[@]}"; do
    case "$command" in
      guidance) /usr/local/bin/remote-dev-agent-guidance status "$REMOTE_DEV_ROLE" ;;
      status) /usr/local/bin/remote-dev-codex-runtime status ;;
      verify) /usr/local/bin/remote-dev-codex-runtime verify ;;
      doctor) /usr/local/bin/remote-dev-doctor ;;
      context7) REMOTE_DEV_ROLE=codex /usr/local/bin/remote-dev-context7 status --menu ;;
      antigravity) REMOTE_DEV_ROLE=antigravity REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 /usr/local/bin/remote-dev-antigravity status --menu ;;
    esac > "$scratch/$project-$index" 2>&1 || {
      echo "ERROR: $REMOTE_DEV_ROLE $project $command failed" >&2
      # Synthetic fixture only; never dump Doctor/private provider output.
      exit 1
    }
    if grep -Eq 'not trusted|Tool not installed for shim|guidance is degraded|runtime status: unavailable|runtime full integrity: unavailable' "$scratch/$project-$index"; then
      echo "ERROR: $project $command inherited project Python resolution" >&2; exit 1
    fi
    index=$((index + 1))
  done
  [[ "$("$admin_python" -I -c 'import sys; print(sys.version); print(sys.prefix)')" == "$image_identity" ]]
  snapshot "$MISE_STATE_DIR" /root/.local/state/mise > "$scratch/state-after"
  cmp "$scratch/state-before" "$scratch/state-after"
}
# Warm ordinary project-resolution tracking before the control-plane snapshot.
python --version >/dev/null
node --version >/dev/null
uv --version >/dev/null
probe_control_plane neutral
for project in unsafe missing; do
  cd "$scratch/$project"
  for cmd in python python3; do
    if "$cmd" --version > "$scratch/error" 2>&1; then
      echo "ERROR: $project ordinary $cmd unexpectedly succeeded" >&2; exit 1
    fi
    if [[ "$project" == unsafe ]]; then
      grep -Fq 'not trusted' "$scratch/error"
    else
      grep -Fq 'Tool not installed for shim' "$scratch/error"
    fi
    if grep -Eqi 'installing|downloading' "$scratch/error"; then exit 1; fi
  done
  probe_control_plane "$project"
done
# Real mise shims select the installed private fixture, for both command names.
export MISE_DATA_DIR="$scratch/store"
cd "$scratch/selected"
for cmd in python python3; do
  [[ "$("$cmd" -c 'import sys; print(sys.prefix)')" == "$scratch/store/installs/python/3.14.999" ]]
done
probe_control_plane selected
# Reconciliation is explicit and may change only the provider-owned guidance.
cd "$scratch/unsafe"
snapshot "$MISE_STATE_DIR" /root/.local/state/mise > "$scratch/state-before"
/usr/local/bin/remote-dev-agent-guidance reconcile "$REMOTE_DEV_ROLE" >/dev/null
/usr/local/bin/remote-dev-agent-guidance status "$REMOTE_DEV_ROLE" | grep -Eq 'guidance: current$'
snapshot "$MISE_STATE_DIR" /root/.local/state/mise > "$scratch/state-after"
cmp "$scratch/state-before" "$scratch/state-after"
snapshot "$scratch/unsafe" "$scratch/missing" "$scratch/selected" "$scratch/store" > "$scratch/projects-after"
cmp "$scratch/projects-before" "$scratch/projects-after"
snapshot /opt/remote-dev/mise /usr/local/lib/remote-dev/python > "$scratch/image-after"
cmp "$scratch/image-before" "$scratch/image-after"
[[ ! -e "$scratch/executed-project" && ! -e "$MISE_STATE_DIR/fallback" ]]
echo "Administrative Python isolation ($REMOTE_DEV_ROLE): OK"
