#!/usr/bin/env bash
set -euo pipefail

source_file="${REMOTE_DEV_RUN_ANTIGRAVITY:-$(dirname "$0")/run-antigravity.sh}"
workdir="$(mktemp -d)"
trap 'rm -rf -- "$workdir"' EXIT

fixture="$workdir/run-antigravity"
bin_dir="$workdir/bin"
workspace="$workdir/workspace"
project="$workspace/project"
invocations="$workdir/vendor-invocations"
manager_calls="$workdir/manager-calls"
policy_calls="$workdir/policy-calls"
mkdir -p "$bin_dir" "$project"

runtime_lib="$workdir/remote-dev-runtime.sh"
cat >"$runtime_lib" <<'RUNTIME'
remote_dev_resolve_role() { printf '%s\n' antigravity; }
remote_dev_workspace_root() { printf '%s\n' "$WORKSPACE"; }
remote_dev_resolve_project() { printf '%s/%s\n' "$1" "${REMOTE_DEV_PROJECT:-project}"; }
remote_dev_enter_project() { builtin cd -P -- "$2"; }
remote_dev_assert_project_git_boundary() { return 0; }
remote_dev_recover_safe_cwd() { builtin cd -P -- /; }
remote_dev_runtime_error() { printf 'ERROR: %s\n' "$*" >&2; }
RUNTIME

vendor="$bin_dir/agy"
cat >"$vendor" <<'VENDOR'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$REMOTE_DEV_TEST_VENDOR_INVOCATIONS"
VENDOR
chmod 0755 "$vendor"

manager="$bin_dir/remote-dev-antigravity"
cat >"$manager" <<'MANAGER'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$REMOTE_DEV_TEST_MANAGER_CALLS"
case "${1:-}" in
  path) printf '%s\n' "$REMOTE_DEV_TEST_VENDOR" ;;
  verify) printf '%s\n' 'Antigravity runtime integrity: OK' ;;
  *) exit 2 ;;
esac
MANAGER
chmod 0755 "$manager"

policy="$bin_dir/remote-dev-antigravity-policy"
cat >"$policy" <<'POLICY'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$REMOTE_DEV_TEST_POLICY_CALLS"
case "${1:-}" in
  status|check-guarded)
    if [[ "${REMOTE_DEV_TEST_GUARDED_CONFLICT:-0}" == 1 ]]; then
      echo 'Antigravity guarded compatibility: CONFLICT (toolPermission=always-proceed, artifactReviewPolicy=default)'
      exit 3
    fi
    echo 'Antigravity guarded compatibility: OK (toolPermission=default, artifactReviewPolicy=default)'
    ;;
  *) exit 2 ;;
esac
POLICY
chmod 0755 "$policy"

secure="$bin_dir/secure-persistent-state"
cat >"$secure" <<'SECURE'
#!/usr/bin/env bash
exit 0
SECURE
chmod 0755 "$secure"

python3 - "$source_file" "$fixture" "$runtime_lib" "$manager" "$policy" "$secure" <<'PY'
from pathlib import Path
import sys

source, destination, runtime_lib, manager, policy, secure = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
replacements = {
    "readonly manager=/usr/local/bin/remote-dev-antigravity": f"readonly manager={manager}",
    "readonly policy_helper=/usr/local/bin/remote-dev-antigravity-policy": f"readonly policy_helper={policy}",
    "readonly secure_state=/usr/local/bin/secure-persistent-state": f"readonly secure_state={secure}",
    "readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh": f"readonly runtime_lib={runtime_lib}",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"missing fixture anchor: {old}")
    text = text.replace(old, new)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture"

common_env=(
  WORKSPACE="$workspace"
  REMOTE_DEV_PROJECT=project
  REMOTE_DEV_ANTIGRAVITY_OAUTH_HELPER=0
  REMOTE_DEV_TEST_VENDOR="$vendor"
  REMOTE_DEV_TEST_VENDOR_INVOCATIONS="$invocations"
  REMOTE_DEV_TEST_MANAGER_CALLS="$manager_calls"
  REMOTE_DEV_TEST_POLICY_CALLS="$policy_calls"
)

run_fixture() {
  local deployment_mode="$1"
  shift
  if [[ "$deployment_mode" == __unset__ ]]; then
    env -u REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE "${common_env[@]}" "$fixture" "$@"
  else
    env REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE="$deployment_mode" "${common_env[@]}" "$fixture" "$@"
  fi
}

rm -f "$manager_calls" "$policy_calls"
output="$(run_fixture __unset__ --print-policy)"
grep -Fxq 'Antigravity approval mode: autonomous' <<<"$output"
grep -Fxq 'Mode source: default' <<<"$output"
grep -Fxq 'Approval behavior: vendor permission/review bypass for this launch' <<<"$output"
grep -Fxq 'Antigravity guarded compatibility: OK (toolPermission=default, artifactReviewPolicy=default)' <<<"$output"
[[ ! -e "$manager_calls" ]]
[[ "$(cat "$policy_calls")" == status ]]

rm -f "$invocations" "$manager_calls" "$policy_calls"
run_fixture __unset__ --continue
[[ "$(cat "$invocations")" == '--dangerously-skip-permissions --continue' ]]
grep -Fxq path "$manager_calls"
grep -Fxq verify "$manager_calls"
if grep -Fxq check-guarded "$policy_calls" 2>/dev/null; then
  echo 'ERROR: autonomous launch unexpectedly required guarded compatibility' >&2
  exit 1
fi

rm -f "$invocations" "$manager_calls" "$policy_calls"
run_fixture guarded --continue
[[ "$(cat "$invocations")" == '--continue' ]]
grep -Fxq check-guarded "$policy_calls"
if grep -Fq -- '--dangerously-skip-permissions' "$invocations"; then
  echo 'ERROR: guarded launch received the autonomous bypass' >&2
  exit 1
fi

rm -f "$invocations" "$manager_calls" "$policy_calls"
run_fixture guarded --approval-mode autonomous --continue
[[ "$(cat "$invocations")" == '--dangerously-skip-permissions --continue' ]]

rm -f "$invocations" "$manager_calls" "$policy_calls"
run_fixture autonomous --approval-mode guarded --continue
[[ "$(cat "$invocations")" == '--continue' ]]
grep -Fxq check-guarded "$policy_calls"

set +e
bad_output="$(run_fixture __unset__ --approval-mode invalid 2>&1)"
bad_status=$?
set -e
[[ "$bad_status" == 2 ]]
grep -Fq 'unsupported per-launch approval mode' <<<"$bad_output"

set +e
bypass_output="$(run_fixture guarded --dangerously-skip-permissions 2>&1)"
bypass_status=$?
set -e
[[ "$bypass_status" == 2 ]]
grep -Fq 'owns the approval policy; refusing argument: --dangerously-skip-permissions' <<<"$bypass_output"

set +e
bypass_eq_output="$(run_fixture guarded --dangerously-skip-permissions=true 2>&1)"
bypass_eq_status=$?
set -e
[[ "$bypass_eq_status" == 2 ]]
grep -Fq 'refusing argument: --dangerously-skip-permissions=true' <<<"$bypass_eq_output"

rm -f "$invocations" "$manager_calls" "$policy_calls"
set +e
conflict_output="$(env REMOTE_DEV_TEST_GUARDED_CONFLICT=1 REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=guarded "${common_env[@]}" "$fixture" --continue 2>&1)"
conflict_status=$?
set -e
[[ "$conflict_status" == 2 ]]
grep -Fq 'cannot guarantee guarded Antigravity semantics' <<<"$conflict_output"
grep -Fq 'repair-guarded --yes' <<<"$conflict_output"
[[ ! -e "$invocations" ]]
[[ ! -e "$manager_calls" ]]

rm -f "$invocations" "$manager_calls" "$policy_calls"
run_fixture __unset__ --mode=plan
[[ "$(cat "$invocations")" == '--dangerously-skip-permissions --mode=plan' ]]
if grep -Fq -- '--sandbox' "$invocations" || grep -Fq -- '--mode=accept-edits' "$invocations"; then
  echo 'ERROR: managed autonomous mode injected unrelated vendor policy flags' >&2
  exit 1
fi

echo 'Antigravity managed autonomous/guarded launch policy: OK'
