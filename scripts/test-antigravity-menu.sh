#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-$(dirname "$0")/remote-dev-menu.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture_menu="$workdir/remote-dev-menu"
runtime_lib="$workdir/remote-dev-runtime.sh"
bin_dir="$workdir/bin"
invocations="$workdir/invocations"
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
{
  printf '[project=%s]' "${REMOTE_DEV_PROJECT:-}"
  for argument in "$@"; do
    printf '[%s]' "$argument"
  done
  printf '\n'
} >>"$REMOTE_DEV_MENU_INVOCATIONS"
RUNNER

cat >"$bin_dir/remote-dev-antigravity" <<'MANAGER'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Antigravity: 1.1.10 (official and reviewed)'
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
    "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh":
        f"runtime_lib={runtime_lib}",
    "/usr/local/bin/run-antigravity": str(bin_dir / "run-antigravity"),
    "/usr/local/bin/remote-dev-antigravity": str(bin_dir / "remote-dev-antigravity"),
    "/usr/local/bin/remote-dev-install-antigravity":
        str(bin_dir / "remote-dev-install-antigravity"),
    "/usr/local/bin/remote-dev-update-antigravity":
        str(bin_dir / "remote-dev-update-antigravity"),
    "/usr/local/bin/secure-persistent-state":
        str(bin_dir / "secure-persistent-state"),
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_menu"

output="$workdir/output"
# Interactive actions pause before returning to the menu, so each exercised action
# is followed by one throwaway input consumed by that pause.
printf '1\n1\n2\n2\n3\n3\n6\n6\n7\n7\n5\n5\n8\n8\n9\n9\n13\n' | env \
  PATH="$bin_dir:$PATH" \
  WORKSPACE="$workdir/workspace" \
  REMOTE_DEV_MENU_INVOCATIONS="$invocations" \
  REMOTE_DEV_MENU_HARDENING_CALLS="$hardening_calls" \
  "$fixture_menu" >"$output" 2>&1

mapfile -t calls <"$invocations"
[[ "${#calls[@]}" == 3 ]]
[[ "${calls[0]}" == '[project=project]' ]]
[[ "${calls[1]}" == '[project=project][--continue]' ]]
[[ "${calls[2]}" == '[project=project]' ]]
[[ "$(wc -l <"$hardening_calls")" == 5 ]]
grep -Fxq 'Project: project' "$output"
grep -Fxq 'Google exposes the full conversation picker only inside the TUI.' "$output"
grep -Fxq 'Choose 3, then type /resume after Antigravity opens to browse conversations.' "$output"
grep -Fxq '1) Start Antigravity' "$output"
grep -Fxq '2) Continue latest Antigravity conversation (current project)' "$output"
grep -Fxq '3) Browse/resume Antigravity conversations (current project)' "$output"
grep -Fxq '4) Projects...' "$output"
grep -Fxq '5) Launch/approval options [not available]' "$output"
grep -Fxq '6) Install Antigravity from Google' "$output"
grep -Fxq '7) Update Antigravity from Google' "$output"
grep -Fxq '8) Context7 integration [pending #95]' "$output"
grep -Fxq '9) Antigravity sign-in [handled during launch]' "$output"
grep -Fxq '10) Sign in to GitHub CLI' "$output"
grep -Fxq '11) Run diagnostics' "$output"
grep -Fxq '12) Open a login shell' "$output"
grep -Fxq '13) Exit this tmux session' "$output"
grep -Fxq 'Antigravity does not currently expose a Remote Dev-reviewed launch/approval option.' "$output"
grep -Fxq 'Context7 for Antigravity is not implemented yet; see #95.' "$output"
grep -Fxq 'Antigravity authentication is currently handled by the vendor flow during launch.' "$output"
if grep -Fq -- '--remote-dev-open-resume-picker' "$invocations"; then
  echo 'ERROR: menu still invokes the screen-scraping Antigravity picker helper' >&2
  exit 1
fi

echo 'Project-scoped supported Antigravity resume menu: OK'
