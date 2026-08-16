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

run_and_expect() {
  local expected="$1"
  shift
  : >"$capture"
  CAPTURE="$capture" "$@" >/dev/null 2>&1
  actual="$(cat -- "$capture")"
  if [[ "$actual" != "$expected" ]]; then
    printf 'Unexpected Context7 entrypoint dispatch.\nExpected:\n%s\nActual:\n%s\n' \
      "$expected" "$actual" >&2
    exit 1
  fi
}

run_and_expect $'manager\nstatus\n--menu' "$entrypoint" status --menu
run_and_expect $'manager\ninstall\n--yes\n--anonymous' \
  "$entrypoint" install --yes --anonymous

: >"$capture"
printf '1\n' | CAPTURE="$capture" "$entrypoint" install >/dev/null 2>&1
[[ "$(cat -- "$capture")" == $'device-login\n--yes' ]]

: >"$capture"
printf '2\n' | CAPTURE="$capture" "$entrypoint" repair >/dev/null 2>&1 || true
[[ "$(cat -- "$capture")" == $'manager\nrepair' ]]

: >"$capture"
printf '3\n' | CAPTURE="$capture" "$entrypoint" install >/dev/null 2>&1
[[ "$(cat -- "$capture")" == $'manager\ninstall\n--yes' ]]

: >"$capture"
printf '4\n' | CAPTURE="$capture" "$entrypoint" repair >/dev/null 2>&1
[[ "$(cat -- "$capture")" == $'manager\nrepair\n--yes\n--anonymous' ]]

if printf '5\n' | CAPTURE="$capture" "$entrypoint" install >/dev/null 2>&1; then
  echo 'Context7 entrypoint cancellation unexpectedly succeeded' >&2
  exit 1
fi

if printf '99\n' | CAPTURE="$capture" "$entrypoint" install >/dev/null 2>&1; then
  echo 'Context7 entrypoint accepted an invalid authentication choice' >&2
  exit 1
fi

bash -n "$source_entrypoint"
echo 'Context7 onboarding entrypoint regressions: OK'
