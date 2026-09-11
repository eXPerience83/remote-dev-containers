#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-$(dirname "$0")/remote-dev-menu.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture_menu="$workdir/remote-dev-menu"
runtime_lib="$workdir/remote-dev-runtime.sh"
bin_dir="$workdir/bin"
invocations="$workdir/invocations"
policy_calls="$workdir/policy-calls"
preset_state="$workdir/guarded-preset"
hardening_calls="$workdir/hardening-calls"
mkdir -p "$bin_dir" "$workdir/workspace/project"

cat >"$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() {
  printf '%s\n' antigravity
}

remote_dev_validate_workspace_root() {
  [[ "$1" == /* && -d "$1" && ! -L "$1" ]] || return 2
  printf '%s\n' "$1"
}

remote_dev_recover_safe_cwd() {
  builtin cd -P -- /
}

remote_dev_validate_project_name() {
  local name="$1"
  (( ${#name} >= 1 && ${#name} <= 128 )) || return 2
  [[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 2
  printf '%s\n' "$name"
}

remote_dev_list_projects() {
  local path name
  for path in "$1"/*; do
    [[ -d "$path" && ! -L "$path" ]] || continue
    name="${path##*/}"
    remote_dev_validate_project_name "$name" >/dev/null 2>&1 || continue
    printf '%s\n' "$name"
  done | LC_ALL=C sort
}

remote_dev_project_path() {
  remote_dev_validate_project_name "$2" >/dev/null || return 2
  [[ -d "$1/$2" && ! -L "$1/$2" ]] || return 2
  printf '%s/%s\n' "$1" "$2"
}

remote_dev_create_project() {
  remote_dev_validate_project_name "$2" >/dev/null || return 2
  [[ ! -e "$1/$2" && ! -L "$1/$2" ]] || return 2
  mkdir -- "$1/$2"
  printf '%s/%s\n' "$1" "$2"
}

remote_dev_delete_project() {
  [[ "$2" == "$3" ]] || return 2
  remote_dev_project_path "$1" "$2" >/dev/null || return 2
  rm -rf -- "$1/$2"
}
RUNTIME

cat >"$bin_dir/run-antigravity" <<'RUNNER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --print-policy ]]; then
  mode="${REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE:-autonomous}"
  if [[ -n "${REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE:-}" ]]; then
    source=deployment
  else
    source=default
  fi
  if [[ -s "$REMOTE_DEV_MENU_PRESET_STATE" ]]; then
    preset="$(cat "$REMOTE_DEV_MENU_PRESET_STATE")"
    tool="$preset"
  else
    preset='request-review (vendor default)'
    tool=default
  fi
  printf '%s\n' \
    "Antigravity approval mode: $mode" \
    "Approval behavior: test" \
    "Mode source: $source" \
    "Antigravity guarded compatibility: OK (toolPermission=$tool, artifactReviewPolicy=default, agentMode=default, fine-grained rules=none)" \
    "Antigravity guarded preset: $preset" \
    'Antigravity guarded policy source: settings.json' \
    'Antigravity fine-grained permissions: user-managed and preserved'
  exit 0
fi
{
  printf '[project=%s]' "${REMOTE_DEV_PROJECT:-}"
  for argument in "$@"; do
    printf '[%s]' "$argument"
  done
  printf '\n'
} >>"$REMOTE_DEV_MENU_INVOCATIONS"
RUNNER

cat >"$bin_dir/remote-dev-antigravity-policy" <<'POLICY'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  set-preset)
    case "${2:-}" in
      request-review|strict) ;;
      *) exit 2 ;;
    esac
    printf '%s\n' "$2" >"$REMOTE_DEV_MENU_PRESET_STATE"
    printf '[set-preset][%s]\n' "$2" >>"$REMOTE_DEV_MENU_POLICY_CALLS"
    printf '%s\n' \
      "Antigravity guarded preset updated: $2" \
      "Antigravity guarded compatibility: OK (toolPermission=$2, artifactReviewPolicy=default, agentMode=default, fine-grained rules=none)" \
      "Antigravity guarded preset: $2" \
      'Antigravity guarded policy source: settings.json' \
      'Antigravity fine-grained permissions: user-managed and preserved'
    ;;
  status|check-guarded)
    exit 0
    ;;
  *) exit 2 ;;
esac
POLICY

cat >"$bin_dir/remote-dev-antigravity" <<'MANAGER'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Antigravity: 1.1.28 (official and reviewed)'
MANAGER

for command in remote-dev-install-antigravity remote-dev-update-antigravity; do
  cat >"$bin_dir/$command" <<'ACTION'
#!/usr/bin/env bash
exit 0
ACTION
  chmod 0755 "$bin_dir/$command"
done

cat >"$bin_dir/secure-persistent-state" <<'SECURE'
#!/usr/bin/env bash
set -euo pipefail
printf 'hardened\n' >>"$REMOTE_DEV_MENU_HARDENING_CALLS"
SECURE

cat >"$bin_dir/remote-dev-version" <<'VERSION'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --check) exit 0 ;;
  --menu) printf '%s\n' 'Image: test @ 0123456789ab' ;;
  *) exit 2 ;;
esac
VERSION

cat >"$bin_dir/clear" <<'CLEAR'
#!/usr/bin/env bash
exit 0
CLEAR

chmod 0755 "$bin_dir"/*

python3 - "$menu_source" "$fixture_menu" "$runtime_lib" "$bin_dir" <<'PY'
from pathlib import Path
import sys

source, destination, runtime_lib, bin_dir = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh": f"runtime_lib={runtime_lib}",
    "/usr/local/bin/run-antigravity": str(bin_dir / "run-antigravity"),
    "/usr/local/bin/remote-dev-antigravity-policy": str(bin_dir / "remote-dev-antigravity-policy"),
    "/usr/local/bin/remote-dev-antigravity": str(bin_dir / "remote-dev-antigravity"),
    "/usr/local/bin/remote-dev-install-antigravity": str(bin_dir / "remote-dev-install-antigravity"),
    "/usr/local/bin/remote-dev-update-antigravity": str(bin_dir / "remote-dev-update-antigravity"),
    "/usr/local/bin/secure-persistent-state": str(bin_dir / "secure-persistent-state"),
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_menu"

output="$workdir/output"
printf '1\n\n2\n\n4\n3\n1\n\n4\n4\n\n5\n\n6\n1\n\n12\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1

mapfile -t calls <"$invocations"
[[ "${#calls[@]}" == 4 ]]
[[ "${calls[0]}" == '[project=project]' ]]
[[ "${calls[1]}" == '[project=project][--continue]' ]]
[[ "${calls[2]}" == '[project=project][--approval-mode][guarded]' ]]
[[ "${calls[3]}" == '[project=project]' ]]
mapfile -t preset_calls <"$policy_calls"
[[ "${#preset_calls[@]}" == 2 ]]
[[ "${preset_calls[0]}" == '[set-preset][request-review]' ]]
[[ "${preset_calls[1]}" == '[set-preset][strict]' ]]
[[ "$(cat "$preset_state")" == strict ]]
[[ "$(wc -l <"$hardening_calls")" == 6 ]]
grep -Fxq 'Antigravity approval mode: autonomous' "$output"
grep -Fxq 'Next launch mode: configured (autonomous)' "$output"
grep -Fxq 'Next launch mode: guarded (one launch)' "$output"
grep -Fxq 'Antigravity guarded preset: request-review (vendor default)' "$output"
grep -Fxq 'Antigravity guarded preset: request-review' "$output"
grep -Fxq 'Antigravity guarded preset: strict' "$output"
grep -Fxq 'Antigravity fine-grained permissions: user-managed and preserved' "$output"
grep -Fxq 'Project: project' "$output"
grep -Fxq '1) Start Antigravity (use /resume to browse/resume older conversations)' "$output"
grep -Fxq '2) Continue latest Antigravity conversation (current project)' "$output"
grep -Fxq '3) Projects...' "$output"
grep -Fxq '4) Approval settings...' "$output"
grep -Fxq '4) Set Guarded preset: request-review (recommended)' "$output"
grep -Fxq '5) Set Guarded preset: strict (more restrictive)' "$output"
grep -Fxq '5) Install Antigravity from Google' "$output"
grep -Fxq '6) Update Antigravity from Google' "$output"
grep -Fxq '7) Context7 integration [pending #95]' "$output"
grep -Fxq '8) Antigravity sign-in [handled during launch]' "$output"
grep -Fxq '9) Sign in to GitHub CLI' "$output"
grep -Fxq '10) Run diagnostics' "$output"
grep -Fxq '11) Open a login shell' "$output"
grep -Fxq '12) Exit this tmux session' "$output"
if grep -Fq 'Launch/approval options [not available]' "$output"; then
  echo 'ERROR: Antigravity menu still marks approval mode unavailable' >&2
  exit 1
fi
if grep -Fq 'Browse/resume Antigravity conversations' "$output"; then
  echo 'ERROR: menu still exposes a separate Antigravity browse action' >&2
  exit 1
fi
if grep -Fq -- '--remote-dev-open-resume-picker' "$invocations"; then
  echo 'ERROR: menu still invokes the screen-scraping Antigravity picker helper' >&2
  exit 1
fi

echo 'Antigravity approval settings, guarded presets and vendor-native continue: OK'

mkdir -p "$workdir/workspace/second-project"
rm -f "$invocations" "$hardening_calls"
printf '3\n1\n2\n1\n\n12\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1

mapfile -t calls <"$invocations"
[[ "${#calls[@]}" == 1 ]]
[[ "${calls[0]}" == '[project=second-project]' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fxq 'Project: second-project' "$output"
echo 'Successful project selection returns to Antigravity for immediate Start: OK'

rm -f "$invocations" "$hardening_calls"
printf '3\n2\ncreated-project\n\n1\n\n12\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1

created_project_path="$workdir/workspace/created-project"
[[ -d "$created_project_path" ]]
mapfile -t calls <"$invocations"
[[ "${#calls[@]}" == 1 ]]
[[ "${calls[0]}" == '[project=created-project]' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fq "Created project: $created_project_path" "$output"
grep -Fxq 'Project: created-project' "$output"
echo 'Successful project creation returns to Antigravity for immediate Start: OK'
