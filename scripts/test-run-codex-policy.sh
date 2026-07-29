#!/usr/bin/env bash
set -euo pipefail

workdir="$(mktemp -d)"
cleanup() {
  rm -rf "$workdir"
}
trap cleanup EXIT

cat > "$workdir/codex" <<'FAKE_CODEX'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$REMOTE_DEV_CODEX_ARGS_FILE"
FAKE_CODEX
chmod 0755 "$workdir/codex"

args_file="$workdir/args"
REMOTE_DEV_CODEX_ARGS_FILE="$args_file" \
PATH="$workdir:$PATH" \
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

echo 'Codex launcher arguments: OK'
