#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source_entrypoint="$repo_root/scripts/remote-dev-context7-entrypoint.sh"

temp_root="$(mktemp -d)"
trap 'rm -rf -- "$temp_root"' EXIT

entrypoint="$temp_root/remote-dev-context7"
manager="$temp_root/manager.sh"
device_login="$temp_root/device-login.sh"
capture="$temp_root/capture"

cp -- "$source_entrypoint" "$entrypoint"
sed -i \
  -e "s|readonly manager=/usr/local/lib/remote-dev/remote-dev-context7.py|readonly manager=$manager|" \
  -e "s|readonly device_login=/usr/local/bin/remote-dev-context7-device-login|readonly device_login=$device_login|" \
  -e 's|readonly python=/opt/remote-dev/mise/shims/python|readonly python=/bin/bash|' \
  "$entrypoint"
chmod 0755 "$entrypoint"

cat >"$manager" <<'MANAGER'
#!/usr/bin/env bash
set -euo pipefail
printf 'manager' >"$CAPTURE"
printf '\n%s' "$@" >>"$CAPTURE"
MANAGER

cat >"$device_login" <<'LOGIN'
#!/usr/bin/env bash
set -euo pipefail
printf 'device-login' >"$CAPTURE"
printf '\n%s' "$@" >>"$CAPTURE"
LOGIN
chmod 0755 "$manager" "$device_login"

assert_capture() {
  local expected="$1"
  local label="$2"
  local actual
  actual="$(cat -- "$capture")"
  if [[ "$actual" != "$expected" ]]; then
    printf 'Unexpected Context7 entrypoint dispatch (%s).\nExpected:\n%s\nActual:\n%s\n' \
      "$label" "$expected" "$actual" >&2
    exit 1
  fi
}

run_and_expect() {
  local expected="$1"
  shift
  : >"$capture"
  CAPTURE="$capture" "$@" >/dev/null 2>&1
  assert_capture "$expected" "direct invocation"
}

run_interactive_choice() {
  local choice="$1"
  local command="$2"
  printf '%s\n' "$choice" | \
    CAPTURE="$capture" script -q -e -f -c "$entrypoint $command" /dev/null >/dev/null 2>&1
}

choose_and_expect() {
  local choice="$1"
  local command="$2"
  local expected="$3"
  : >"$capture"
  run_interactive_choice "$choice" "$command"
  assert_capture "$expected" "interactive choice $choice"
}

run_and_expect $'manager\nstatus\n--menu' "$entrypoint" status --menu
run_and_expect $'manager\ninstall\n--yes\n--anonymous' \
  "$entrypoint" install --yes --anonymous

# Plain install/repair with redirected stdin is automation, not the onboarding menu.
: >"$capture"
printf '1\n' | CAPTURE="$capture" "$entrypoint" install >/dev/null 2>&1
assert_capture $'manager\ninstall' "redirected install"

choose_and_expect 1 install $'device-login\n--yes'
choose_and_expect 2 repair $'manager\nrepair'
choose_and_expect 3 install $'manager\ninstall\n--yes'
choose_and_expect 4 repair $'manager\nrepair\n--yes\n--anonymous'

: >"$capture"
if run_interactive_choice 5 install; then
  echo 'Context7 entrypoint cancellation unexpectedly succeeded' >&2
  exit 1
fi

: >"$capture"
if run_interactive_choice 99 install; then
  echo 'Context7 entrypoint accepted an invalid authentication choice' >&2
  exit 1
fi

bash -n "$source_entrypoint"
echo 'Context7 onboarding entrypoint regressions: OK'
