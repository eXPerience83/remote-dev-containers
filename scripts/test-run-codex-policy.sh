#!/usr/bin/env bash
set -euo pipefail

workdir="$(mktemp -d)"
pinned_codex=/usr/local/bin/codex
backed_up=0

cleanup() {
  if (( backed_up == 1 )); then
    rm -f "$pinned_codex"
    mv "$workdir/codex.real" "$pinned_codex"
  fi
  rm -rf "$workdir"
}
trap cleanup EXIT

mv "$pinned_codex" "$workdir/codex.real"
backed_up=1

cat > "$pinned_codex" <<'FAKE_PINNED_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$REMOTE_DEV_CODEX_ARGS_FILE"
FAKE_PINNED_CODEX
chmod 0755 "$pinned_codex"

mkdir -p "$workdir/path-bin"
cat > "$workdir/path-bin/codex" <<'FAKE_PATH_CODEX'
#!/usr/bin/env bash
echo 'ERROR: run-codex resolved Codex through PATH' >&2
exit 99
FAKE_PATH_CODEX
chmod 0755 "$workdir/path-bin/codex"

args_file="$workdir/args"
PATH="$workdir/path-bin:$PATH" \
REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
  run-codex resume --last

mapfile -t actual < "$args_file"
expected=(
  --sandbox
  danger-full-access
  --ask-for-approval
  untrusted
  resume
  --last
)

if (( ${#actual[@]} != ${#expected[@]} )); then
  printf 'ERROR: run-codex passed %d arguments, expected %d\n' "${#actual[@]}" "${#expected[@]}" >&2
  printf 'Actual: %q\n' "${actual[@]}" >&2
  exit 1
fi

for index in "${!expected[@]}"; do
  if [[ "${actual[$index]}" != "${expected[$index]}" ]]; then
    printf 'ERROR: run-codex argument %d is %q, expected %q\n' \
      "$index" "${actual[$index]}" "${expected[$index]}" >&2
    exit 1
  fi
done

echo 'Codex launcher arguments and pinned executable: OK'

assert_rejected() {
  local label="$1"
  shift
  local error_file="$workdir/rejected-error"
  local status=0

  rm -f "$args_file" "$error_file"
  set +e
  PATH="$workdir/path-bin:$PATH" \
  REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
    run-codex "$@" >/dev/null 2>"$error_file"
  status=$?
  set -e

  if (( status != 2 )); then
    echo "ERROR: $label returned status $status, expected 2" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
  if [[ -e "$args_file" ]]; then
    echo "ERROR: $label invoked Codex despite the rejected policy override" >&2
    exit 1
  fi
  if ! grep -Fq 'refusing argument:' "$error_file"; then
    echo "ERROR: $label did not explain the rejected policy override" >&2
    cat "$error_file" >&2 || true
    exit 1
  fi
}

assert_rejected 'long sandbox flag' --sandbox read-only
assert_rejected 'short sandbox flag' -s read-only
assert_rejected 'long approval flag' --ask-for-approval never
assert_rejected 'short approval flag' -a never
assert_rejected 'dangerous bypass flag' --dangerously-bypass-approvals-and-sandbox
assert_rejected 'yolo alias' --yolo
assert_rejected 'full-auto shortcut' --full-auto
assert_rejected 'short config sandbox override' -c 'sandbox_mode="read-only"'
assert_rejected 'long config approval override' --config 'approval_policy="never"'
assert_rejected 'inline config sandbox override' '--config=sandbox_mode="workspace-write"'
assert_rejected 'profile config approval override' -c 'profiles.test.approval_policy="never"'

echo 'Codex launcher policy overrides: rejected'
