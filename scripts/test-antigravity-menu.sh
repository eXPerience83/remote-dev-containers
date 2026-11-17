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
context7_calls="$workdir/context7-calls"
shared_calls="$workdir/shared-calls"
manage_calls="$workdir/manage-calls"
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
  if [[ "${REMOTE_DEV_MENU_AGY_POLICY_FAIL:-0}" == 1 ]]; then exit 7; fi
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
    "Antigravity guarded compatibility: ${REMOTE_DEV_MENU_GUARDED_COMPAT:-OK (toolPermission=$tool, artifactReviewPolicy=default, agentMode=default, fine-grained rules=none)}" \
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

cat >"$bin_dir/remote-dev-context7-antigravity" <<'CONTEXT7'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  status)
    [[ "${2:-}" == --menu && "$#" == 2 ]] || exit 2
    echo 'Context7 (Antigravity): not installed'
    ;;
  menu-state)
    [[ "$#" == 1 ]] || exit 2
    printf '%s\n' "${REMOTE_DEV_MENU_AGY_CONTEXT7_STATE:-absent}"
    ;;
  plan)
    [[ "$#" == 1 ]] || exit 2
    echo 'Context7 (Antigravity): NOT INSTALLED; installation available'
    echo plan >>"$REMOTE_DEV_MENU_CONTEXT7_CALLS"
    ;;
  reinstall)
    [[ "$#" == 1 || ( "$#" == 2 && "$2" == --yes ) ]] || exit 2
    echo "$*" >>"$REMOTE_DEV_MENU_CONTEXT7_CALLS"
    ;;
  test|remove)
    [[ "$#" == 2 && "$2" == --yes ]] || exit 2
    echo "$*" >>"$REMOTE_DEV_MENU_CONTEXT7_CALLS"
    ;;
  *) exit 2 ;;
esac
CONTEXT7

cat >"$bin_dir/remote-dev-antigravity" <<'MANAGER'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' "${REMOTE_DEV_MENU_AGY_STATUS:-Antigravity: 1.1.28 (official and reviewed)}"
MANAGER

for command in remote-dev-install-antigravity remote-dev-update-antigravity; do
  cat >"$bin_dir/$command" <<'ACTION'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${0##*/}" >> "$REMOTE_DEV_MENU_MANAGE_CALLS"
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


cat >"$bin_dir/gh" <<'GH'
#!/usr/bin/env bash
set -euo pipefail
printf 'gh:%s\n' "$*" >>"$REMOTE_DEV_MENU_SHARED_CALLS"
GH

cat >"$bin_dir/remote-dev-doctor" <<'DOCTOR'
#!/usr/bin/env bash
set -euo pipefail
printf 'doctor\n' >>"$REMOTE_DEV_MENU_SHARED_CALLS"
DOCTOR

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
    "/usr/local/bin/remote-dev-context7-antigravity": str(bin_dir / "remote-dev-context7-antigravity"),
    "/usr/local/bin/remote-dev-install-antigravity": str(bin_dir / "remote-dev-install-antigravity"),
    "/usr/local/bin/remote-dev-update-antigravity": str(bin_dir / "remote-dev-update-antigravity"),
    "/usr/local/bin/secure-persistent-state": str(bin_dir / "secure-persistent-state"),
    "/usr/local/bin/remote-dev-doctor": str(bin_dir / "remote-dev-doctor"),
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_menu"

output="$workdir/output"
printf '1\n\n2\n\n4\n3\n1\n\n4\n4\ny\n\n5\ny\n\n0\n1\n\n0\n' | env \
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
grep -Fxq '1) Start Antigravity' "$output"
grep -Fxq '2) Continue latest session (current project)' "$output"
grep -Fxq '3) Projects...' "$output"
grep -Fxq '4) Approval settings...' "$output"
grep -Fxq '4) Set Guarded preset: request-review (recommended)' "$output"
grep -Fxq '5) Set Guarded preset: strict (more restrictive)' "$output"
grep -Fxq '5) Manage Antigravity...' "$output"
grep -Fxq '6) MCP integrations...' "$output"
grep -Fxq '7) Sign in to GitHub CLI' "$output"
grep -Fxq '8) Run diagnostics' "$output"
grep -Fxq '9) Open container shell' "$output"
grep -Fxq '0) Exit this tmux session' "$output"
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

rm -f "$invocations" "$hardening_calls"
printf '0\n' | env -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
grep -Fxq 'Approval mode: autonomous (default)' "$output"
if grep -Fq 'Approval behavior:' "$output" || grep -Fq 'Antigravity guarded preset:' "$output"; then
  echo 'ERROR: Antigravity main summary leaked detailed guarded policy' >&2
  exit 1
fi
[[ ! -e "$invocations" ]] && [[ ! -e "$hardening_calls" ]]
echo 'Antigravity main summary is compact and read-only: OK'

printf '4\n0\n0\n' | env \
  REMOTE_DEV_MENU_GUARDED_COMPAT=BLOCKED \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
grep -Fxq 'Guarded compatibility: BLOCKED — see Approval settings' "$output"
grep -Fxq 'Antigravity guarded compatibility: BLOCKED' "$output"
[[ ! -e "$hardening_calls" ]]
echo 'Antigravity guarded BLOCKED remains visible with detail: OK'

printf '0\n' | env \
  REMOTE_DEV_MENU_GUARDED_COMPAT=unavailable \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
grep -Fxq 'Guarded compatibility: UNKNOWN — see Approval settings' "$output"
[[ ! -e "$hardening_calls" ]]
echo 'Antigravity guarded unavailable remains an actionable warning: OK'

set +e
printf '1\n' | env REMOTE_DEV_MENU_AGY_POLICY_FAIL=1 \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
status=$?
set -e
[[ "$status" == 1 ]] || { echo "ERROR: policy inspection failure returned $status" >&2; exit 1; }
grep -Fq 'ERROR: unable to inspect the configured Antigravity approval policy' "$output"
[[ ! -e "$invocations" ]]
echo 'Antigravity policy inspection remains fail-closed: OK'

run_manage_fixture() {
  local input="$1" state="$2"
  rm -f "$manage_calls" "$hardening_calls"
  printf '%s' "$input" | env \
    REMOTE_DEV_MENU_AGY_STATUS="$state" \
    PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
    REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
    REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
    REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
    REMOTE_DEV_MENU_MANAGE_CALLS="$manage_calls" \
    timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
}

run_manage_fixture $'5\n1\n\n2\n\n3\n\n0\n0\n' 'Antigravity: 1.1.28 (official and reviewed)'
[[ "$(cat "$manage_calls")" == 'remote-dev-update-antigravity' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fxq '1) Install from Google [already installed; use Update]' "$output"
grep -Fxq '2) Update from Google' "$output"
grep -Fq 'Install is unavailable in the current runtime state' "$output"
grep -Fq 'sign-in is handled by Google' "$output"

run_manage_fixture $'5\n2\n\n1\n\n0\n0\n' 'Antigravity: not installed'
[[ "$(cat "$manage_calls")" == 'remote-dev-install-antigravity' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fxq '1) Install from Google' "$output"
grep -Fxq '2) Update from Google [unavailable: install first]' "$output"
grep -Fq 'Update is unavailable in the current runtime state' "$output"

run_manage_fixture $'5\n1\n\n2\n\n0\n0\n' \
  'Antigravity: damaged or locally modified (explicit update required)'
[[ "$(cat "$manage_calls")" == 'remote-dev-update-antigravity' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fxq '1) Install from Google [unavailable: use Update to repair]' "$output"

run_manage_fixture $'5\n1\n\n2\n\n0\n0\n' \
  'Antigravity: status unavailable (exit 7)'
[[ ! -e "$manage_calls" ]] && [[ ! -e "$hardening_calls" ]]
grep -Fxq '1) Install from Google [blocked: status unavailable]' "$output"
grep -Fxq '2) Update from Google [blocked: status unavailable]' "$output"

run_manage_fixture $'5\n1\n\n2\n\n0\n0\n' \
  'Antigravity: 1.2.0 (official source; Remote Dev review pending)'
[[ "$(cat "$manage_calls")" == 'remote-dev-update-antigravity' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fxq '1) Install from Google [already installed; use Update]' "$output"
grep -Fq 'review pending' "$output"
grep -Fq 'automatically updated or certified' "$output"

run_manage_fixture $'5\n0\n0\n' 'Antigravity: 1.1.28 (official and reviewed)'
[[ ! -e "$manage_calls" ]] && [[ ! -e "$hardening_calls" ]]
echo 'Antigravity Manage state-aware actions, repair, review-pending and Back: OK'

mkdir -p "$workdir/workspace/second-project"
rm -f "$invocations" "$hardening_calls"
printf '3\n1\n2\n1\n\n0\n' | env \
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

# The project picker must show 0 Back, and Back at each nesting level
# must not launch the agent or harden/mutate any persistent state.
rm -f "$invocations" "$hardening_calls"
printf '3\n1\n0\n0\n0\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ ! -e "$invocations" && ! -e "$hardening_calls" ]]
(( $(grep -Fxc '0) Back' "$output") >= 2 ))
echo 'Antigravity nested project 0 Back does not dispatch an agent: OK'

rm -f "$invocations" "$hardening_calls"
printf '3\n2\ncreated-project\n\n1\n\n0\n' | env \
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

# Context7 uses native vendor OAuth; menu state never opens token storage.
rm -f "$hardening_calls" "$context7_calls"
printf '6\n1\n1\n\n2\ny\n\n3\n\n4\ny\n\n5\n\n0\n0\n0\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=absent \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
mapfile -t context7_actions <"$context7_calls"
[[ "${#context7_actions[@]}" == 4 ]]
[[ "${context7_actions[0]}" == plan ]]
[[ "${context7_actions[1]}" == 'test --yes' ]]
[[ "${context7_actions[2]}" == plan ]]
[[ "${context7_actions[3]}" == 'reinstall --yes' ]]
[[ "$(wc -l <"$hardening_calls")" == 2 ]]
grep -Fq 'Remote Dev — Antigravity — Context7' "$output"
grep -Fq 'Authenticate' "$output"
echo 'Antigravity Context7 guidance, installation and confirmed HTTP test: OK'

rm -f "$hardening_calls" "$context7_calls"
printf '6\n1\n4\n\n5\nREMOVE\n\n0\n0\n0\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=healthy \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ "$(cat "$context7_calls")" == 'remove --yes' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
grep -Fq 'no reinstall is needed' "$output"
echo 'Antigravity Context7 healthy no-op and selective removal: OK'

# Confirmed network tests, including invalid or typed TEST, must cancel
# before invoking the provider binary (and must not trigger hardening).
for decision in n TEST ""; do
  rm -f "$hardening_calls" "$context7_calls"
  printf '6\n1\n2\n%s\n\n0\n0\n0\n' "$decision" | env \
    REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=healthy \
    PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
    REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
    REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
    REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
    REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
    timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
  [[ ! -e "$context7_calls" && ! -e "$hardening_calls" ]]
  grep -Fq 'Context7 test cancelled; no network request was made.' "$output"
done

# Both roles require y/N for initial registration, but keep their
# different authentication schemas (Codex onboarding vs AGY native OAuth).
rm -f "$hardening_calls" "$context7_calls"
printf '6\n1\n4\nn\n\n0\n0\n0\n' | env \
  REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=absent \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ "$(cat "$context7_calls")" == plan ]]
[[ ! -e "$hardening_calls" ]]
grep -Fq 'Context7 installation cancelled; no configuration changes were made.' "$output"

# A repairable AGY registration requires exactly REINSTALL before --yes.
rm -f "$hardening_calls" "$context7_calls"
printf '6\n1\n4\nREINSTALL\n\n0\n0\n0\n' | env \
  REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=repairable \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ "$(cat "$context7_calls")" == $'plan\nreinstall --yes' ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]

rm -f "$hardening_calls" "$context7_calls"
printf '6\n1\n5\nNO\n\n0\n0\n0\n' | env \
  REMOTE_DEV_MENU_AGY_CONTEXT7_STATE=healthy \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_CONTEXT7_CALLS="$context7_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ ! -e "$context7_calls" && ! -e "$hardening_calls" ]]
echo 'Antigravity Context7 consent/repair/removal/cancel end-to-end: OK'

# Declining Guarded preset changes must not call the persistent policy writer.
rm -f "$hardening_calls" "$policy_calls"
printf '4\n4\nn\n\n5\nn\n\n0\n0\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
[[ ! -e "$policy_calls" && ! -e "$hardening_calls" ]]
grep -Fq 'Guarded preset change cancelled' "$output"
echo 'Guarded persistent preset consent/cancellation: OK'

# Shared main-menu login and diagnostics must dispatch identically for AGY.
# Codex's fixture also tests option 9 (container shell); shell has its own role menu.
rm -f "$hardening_calls" "$shared_calls"
printf '7\n\n8\n\n0\n' | env \
  -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE \
  PATH="$bin_dir:$PATH" WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_POLICY_CALLS="$policy_calls" \
  REMOTE_DEV_MENU_PRESET_STATE="$preset_state" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  REMOTE_DEV_MENU_SHARED_CALLS="$shared_calls" \
  timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
mapfile -t shared_actions <"$shared_calls"
[[ "${#shared_actions[@]}" == 3 ]]
[[ "${shared_actions[0]}" == 'gh:auth login --hostname github.com --git-protocol https --web' ]]
[[ "${shared_actions[1]}" == 'gh:auth setup-git' ]]
[[ "${shared_actions[2]}" == doctor ]]
[[ "$(wc -l <"$hardening_calls")" == 1 ]]
echo 'Antigravity common GitHub and diagnostics menu helpers: OK'
