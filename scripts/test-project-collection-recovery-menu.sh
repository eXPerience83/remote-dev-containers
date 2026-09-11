#!/usr/bin/env bash
set -euo pipefail

menu_source="${REMOTE_DEV_MENU:-$(dirname "$0")/remote-dev-menu.sh}"
runtime_lib="${REMOTE_DEV_RUNTIME_LIB:-$(dirname "$0")/lib/remote-dev-runtime.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture_menu="$workdir/remote-dev-menu"
bin_dir="$workdir/bin"
workspace="$workdir/workspace"
project="$workspace/project"
canary="$project/DO_NOT_DELETE"
agent_invocations="$workdir/agent-invocations"
doctor_invocations="$workdir/doctor-invocations"
shell_invocations="$workdir/shell-invocations"
hardening_invocations="$workdir/hardening-invocations"
mkdir -p "$bin_dir" "$project"
printf 'canary\n' >"$canary"
git -C "$workspace" init -q

assert_invocation_count() {
  local file="$1"
  local expected="$2"
  local label="$3"
  local actual=""

  [[ -f "$file" ]] || {
    echo "ERROR: $label recorded no invocations" >&2
    exit 1
  }
  actual="$(wc -l <"$file")"
  [[ "$actual" == "$expected" ]] || {
    echo "ERROR: $label ran $actual times, expected $expected" >&2
    exit 1
  }
}

assert_output_contains() {
  local file="$1"
  local text="$2"

  grep -Fq "$text" "$file" || {
    echo "ERROR: menu output lacked: $text" >&2
    exit 1
  }
}

assert_canary_and_contamination_preserved() {
  [[ -f "$canary" ]] || {
    echo 'ERROR: sibling canary was removed' >&2
    exit 1
  }
  [[ "$(<"$canary")" == canary ]] || {
    echo 'ERROR: sibling canary was modified' >&2
    exit 1
  }
  [[ -d "$workspace/.git" ]] || {
    echo 'ERROR: contaminated collection .git was removed' >&2
    exit 1
  }
}

cat >"$bin_dir/run-codex" <<'CODEX'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --print-policy ]]; then
  printf '%s\n' \
    'Codex approval mode: autonomous' \
    'Codex approval policy: never' \
    'Mode source: default'
  exit 0
fi
printf 'codex' >>"$REMOTE_DEV_TEST_AGENT_INVOCATIONS"
CODEX

cat >"$bin_dir/remote-dev-codex-runtime" <<'CODEX_RUNTIME'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Codex: test'
CODEX_RUNTIME

cat >"$bin_dir/remote-dev-context7" <<'CONTEXT7'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Context7: test'
CONTEXT7

cat >"$bin_dir/remote-dev-antigravity" <<'AGY_STATUS'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == status && "${2:-}" == --menu ]]
printf '%s\n' 'Antigravity: test'
AGY_STATUS

cat >"$bin_dir/run-antigravity" <<'AGY'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == --print-policy ]]; then
  printf '%s\n' \
    'Antigravity approval mode: autonomous' \
    'Approval behavior: vendor permission/review bypass for this launch' \
    'Mode source: default' \
    'Antigravity guarded compatibility: OK (toolPermission=default, artifactReviewPolicy=default)'
  exit 0
fi
printf 'antigravity' >>"$REMOTE_DEV_TEST_AGENT_INVOCATIONS"
AGY

cat >"$bin_dir/remote-dev-version" <<'VERSION'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --check) exit 0 ;;
  --menu) printf '%s\n' 'Image: test' ;;
  *) exit 2 ;;
esac
VERSION

cat >"$bin_dir/remote-dev-doctor" <<'DOCTOR'
#!/usr/bin/env bash
set -euo pipefail
printf 'doctor\n' >>"$REMOTE_DEV_TEST_DOCTOR_INVOCATIONS"
printf '%s\n' 'Workspace collection: CRITICAL — collection root is Git-contaminated or ambiguous'
exit 1
DOCTOR

cat >"$bin_dir/login-shell" <<'SHELL'
#!/usr/bin/env bash
set -euo pipefail
printf 'shell\n' >>"$REMOTE_DEV_TEST_SHELL_INVOCATIONS"
SHELL

cat >"$bin_dir/secure-persistent-state" <<'SECURE'
#!/usr/bin/env bash
set -euo pipefail
printf 'hardened\n' >>"$REMOTE_DEV_TEST_HARDENING_INVOCATIONS"
SECURE

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
    "/usr/local/bin/run-codex": str(bin_dir / "run-codex"),
    "/usr/local/bin/remote-dev-codex-runtime": str(bin_dir / "remote-dev-codex-runtime"),
    "/usr/local/bin/remote-dev-context7": str(bin_dir / "remote-dev-context7"),
    "/usr/local/bin/remote-dev-antigravity": str(bin_dir / "remote-dev-antigravity"),
    "/usr/local/bin/run-antigravity": str(bin_dir / "run-antigravity"),
    "/usr/local/bin/remote-dev-doctor": str(bin_dir / "remote-dev-doctor"),
    "/usr/local/bin/secure-persistent-state": str(bin_dir / "secure-persistent-state"),
    "bash --login": str(bin_dir / "login-shell"),
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_menu"

run_recovery_menu() {
  local role="$1"
  local input="$2"
  local output="$3"
  rm -f \
    "$agent_invocations" \
    "$doctor_invocations" \
    "$shell_invocations" \
    "$hardening_invocations"

  printf '%s' "$input" | env \
    PATH="$bin_dir:$PATH" \
    WORKSPACE="$workspace" \
    REMOTE_DEV_ROLE="$role" \
    REMOTE_DEV_ENABLE_EXPERIMENTAL_ANTIGRAVITY=1 \
    REMOTE_DEV_TEST_AGENT_INVOCATIONS="$agent_invocations" \
    REMOTE_DEV_TEST_DOCTOR_INVOCATIONS="$doctor_invocations" \
    REMOTE_DEV_TEST_SHELL_INVOCATIONS="$shell_invocations" \
    REMOTE_DEV_TEST_HARDENING_INVOCATIONS="$hardening_invocations" \
    timeout --foreground 30s "$fixture_menu" >"$output" 2>&1
}

codex_output="$workdir/codex-output"
# Start and Resume are blocked. Projects remains reachable but selection is
# blocked. Diagnostics and Login shell remain available for recovery.
run_recovery_menu codex $'1\n\n2\n\n3\n1\n4\n10\n\n11\n\n12\n' "$codex_output"
[[ ! -s "$agent_invocations" ]] || {
  echo 'ERROR: Codex was invoked from a contaminated project collection' >&2
  cat "$agent_invocations" >&2
  exit 1
}
assert_invocation_count "$doctor_invocations" 1 'Codex diagnostics'
assert_invocation_count "$shell_invocations" 1 'Codex login shell'
assert_invocation_count "$hardening_invocations" 1 'Codex persistent-state hardening'
assert_output_contains "$codex_output" 'Project: BLOCKED (collection safety check failed; run diagnostics)'
assert_output_contains "$codex_output" 'agent launch is blocked'
assert_output_contains "$codex_output" 'Safety block: project mutations are disabled until the collection is repaired.'
assert_output_contains "$codex_output" 'project selection is blocked'
assert_canary_and_contamination_preserved
echo 'Codex contamination state keeps only recovery actions available: OK'

agy_output="$workdir/antigravity-output"
run_recovery_menu antigravity $'1\n\n2\n\n10\n\n11\n\n12\n' "$agy_output"
[[ ! -s "$agent_invocations" ]] || {
  echo 'ERROR: Antigravity was invoked from a contaminated project collection' >&2
  cat "$agent_invocations" >&2
  exit 1
}
assert_invocation_count "$doctor_invocations" 1 'Antigravity diagnostics'
assert_invocation_count "$shell_invocations" 1 'Antigravity login shell'
assert_invocation_count "$hardening_invocations" 1 'Antigravity persistent-state hardening'
assert_output_contains "$agy_output" 'Project: BLOCKED (collection safety check failed; run diagnostics)'
assert_output_contains "$agy_output" 'agent launch is blocked'
assert_canary_and_contamination_preserved
echo 'Antigravity contamination state keeps only recovery actions available: OK'
