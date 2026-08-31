#!/usr/bin/env bash
set -euo pipefail

launcher="${REMOTE_DEV_LAUNCHER:-/usr/local/bin/remote-dev-launcher}"
workdir="$(mktemp -d)"
log_file="$workdir/launcher.log"
starting_uid="$(id -u)"
launcher_pid=''

free_port() {
  python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
}

stop_launcher() {
  if [[ -n "$launcher_pid" ]]; then
    kill "$launcher_pid" >/dev/null 2>&1 || true
    wait "$launcher_pid" >/dev/null 2>&1 || true
    launcher_pid=''
  fi
}

cleanup() {
  stop_launcher
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

port="$(free_port)"
base_url="http://127.0.0.1:${port}"
secret='synthetic-launcher-secret'

WEB_BIND=127.0.0.1 \
WEB_PORT="$port" \
WEB_BASE_PATH=/launcher \
WEB_USERNAME=remote-dev \
WEB_PASSWORD="$secret" \
WEB_CHECK_ORIGIN=1 \
ALLOW_INSECURE_WEB=0 \
REMOTE_DEV_LAUNCHER_CODEX_PORT=8765 \
REMOTE_DEV_LAUNCHER_CODEX_PATH=/codex \
REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED=1 \
REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PORT=8766 \
REMOTE_DEV_LAUNCHER_ANTIGRAVITY_PATH=/antigravity \
  python "$launcher" >"$log_file" 2>&1 &
launcher_pid=$!

for _ in $(seq 1 50); do
  if curl --fail --silent --show-error "$base_url/launcher/healthz" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    echo 'ERROR: launcher exited before becoming ready' >&2
    cat "$log_file" >&2
    exit 1
  fi
  sleep 0.1
done
curl --fail --silent --show-error "$base_url/launcher/healthz" \
  | grep -Fq '"role":"launcher"'

if [[ "$starting_uid" == 0 ]]; then
  effective_uid="$(ps -o uid= -p "$launcher_pid" | tr -d '[:space:]')"
  [[ "$effective_uid" == 65532 ]] || {
    echo "ERROR: launcher serves as UID $effective_uid instead of 65532" >&2
    cat "$log_file" >&2
    exit 1
  }
fi

status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  "$base_url/launcher/")"
[[ "$status" == 401 ]] || {
  echo "ERROR: unauthenticated launcher returned $status instead of 401" >&2
  exit 1
}

status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --user 'remote-dev:wrong' "$base_url/launcher/")"
[[ "$status" == 401 ]] || {
  echo "ERROR: invalid launcher credentials returned $status instead of 401" >&2
  exit 1
}

non_ascii_basic="$(printf 'rémote:wrong' | base64 -w 0)"
status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --header "Authorization: Basic ${non_ascii_basic}" \
  "$base_url/launcher/")"
[[ "$status" == 401 ]] || {
  echo "ERROR: non-ASCII launcher credentials returned $status instead of 401" >&2
  cat "$log_file" >&2
  exit 1
}
kill -0 "$launcher_pid" 2>/dev/null || {
  echo 'ERROR: malformed credentials crashed the launcher' >&2
  cat "$log_file" >&2
  exit 1
}

status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --user "remote-dev:${secret}" \
  --header 'Origin: http://example.invalid' \
  "$base_url/launcher/")"
[[ "$status" == 403 ]] || {
  echo "ERROR: mismatched launcher origin returned $status instead of 403" >&2
  exit 1
}

page="$workdir/page.html"
headers="$workdir/headers.txt"
curl --fail --silent --show-error \
  --user "remote-dev:${secret}" \
  --header "Origin: ${base_url}" \
  --dump-header "$headers" \
  --output "$page" \
  "$base_url/launcher/"

grep -Fq '"port":8765' "$page"
grep -Fq '"path":"/codex"' "$page"
grep -Fq 'authenticates independently' "$page"
grep -Fq 'Open Antigravity (experimental)' "$page"
grep -Fq '"port":8766' "$page"
grep -Fq '"path":"/antigravity"' "$page"
grep -Fq 'separate authentication, workspace and credentials' "$page"
if grep -Fq "$secret" "$page"; then
  echo 'ERROR: launcher page exposed the web password' >&2
  exit 1
fi
grep -Fiq "content-security-policy: default-src 'none'" "$headers"
grep -Fiq "script-src 'nonce-" "$headers"

status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  --request POST --user "remote-dev:${secret}" "$base_url/launcher/")"
[[ "$status" == 405 ]] || {
  echo "ERROR: launcher POST returned $status instead of 405" >&2
  exit 1
}

stop_launcher
insecure_port="$(free_port)"
insecure_url="http://127.0.0.1:${insecure_port}"
insecure_log="$workdir/launcher-no-auth.log"
WEB_BIND=127.0.0.1 \
WEB_PORT="$insecure_port" \
WEB_BASE_PATH=/ \
WEB_CHECK_ORIGIN=1 \
ALLOW_INSECURE_WEB=1 \
REMOTE_DEV_LAUNCHER_CODEX_PORT=7681 \
  python "$launcher" >"$insecure_log" 2>&1 &
launcher_pid=$!

for _ in $(seq 1 50); do
  if curl --fail --silent --show-error "$insecure_url/healthz" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$launcher_pid" 2>/dev/null; then
    echo 'ERROR: unauthenticated launcher exited before becoming ready' >&2
    cat "$insecure_log" >&2
    exit 1
  fi
  sleep 0.1
done
status="$(curl --silent --output "$workdir/no-auth-page.html" --write-out '%{http_code}' \
  "$insecure_url/")"
[[ "$status" == 200 ]] || {
  echo "ERROR: optional unauthenticated launcher returned $status instead of 200" >&2
  cat "$insecure_log" >&2
  exit 1
}
grep -Fq 'Open Codex' "$workdir/no-auth-page.html"
if grep -Fq 'Open Antigravity' "$workdir/no-auth-page.html"; then
  echo 'ERROR: disabled Antigravity route was advertised' >&2
  exit 1
fi
stop_launcher

for delimiter in newline carriage-return; do
  malformed_log="$workdir/malformed-$delimiter.log"
  malformed_status=0
  if [[ "$delimiter" == newline ]]; then
    malformed_password=$'synthetic-first-line\nsynthetic-second-line'
  else
    malformed_password=$'synthetic-first-line\rsynthetic-second-line'
  fi
  WEB_PASSWORD="$malformed_password" ALLOW_INSECURE_WEB=0 python "$launcher" \
    >/dev/null 2>"$malformed_log" || malformed_status=$?
  [[ "$malformed_status" == 2 ]] || {
    echo "ERROR: malformed launcher password returned $malformed_status instead of 2" >&2
    cat "$malformed_log" >&2
    exit 1
  }
  grep -Fq 'web password must be a single line without NUL' "$malformed_log"
  if grep -Fq 'synthetic-first-line' "$malformed_log"; then
    echo 'ERROR: malformed launcher password was echoed to logs' >&2
    exit 1
  fi
done

invalid_log="$workdir/invalid.log"
invalid_status=0
ALLOW_INSECURE_WEB=1 WEB_PORT=70000 python "$launcher" \
  > /dev/null 2>"$invalid_log" || invalid_status=$?
[[ "$invalid_status" == 2 ]] || {
  echo "ERROR: invalid launcher configuration returned $invalid_status instead of 2" >&2
  cat "$invalid_log" >&2
  exit 1
}
grep -Fq 'WEB_PORT must be between 1 and 65535' "$invalid_log"

unsafe_path_log="$workdir/unsafe-path.log"
unsafe_path_status=0
ALLOW_INSECURE_WEB=1 \
REMOTE_DEV_LAUNCHER_CODEX_PATH='/codex</script>' \
  python "$launcher" > /dev/null 2>"$unsafe_path_log" || unsafe_path_status=$?
[[ "$unsafe_path_status" == 2 ]] || {
  echo "ERROR: unsafe route path returned $unsafe_path_status instead of 2" >&2
  cat "$unsafe_path_log" >&2
  exit 1
}
grep -Fq 'absolute URL path containing only RFC 3986 path characters' "$unsafe_path_log"

embedded_port_log="$workdir/embedded-port.log"
embedded_port_status=0
ALLOW_INSECURE_WEB=1 \
REMOTE_DEV_LAUNCHER_CODEX_HOST='codex.example.com:8443' \
  python "$launcher" > /dev/null 2>"$embedded_port_log" || embedded_port_status=$?
[[ "$embedded_port_status" == 2 ]] || {
  echo "ERROR: host with embedded port returned $embedded_port_status instead of 2" >&2
  cat "$embedded_port_log" >&2
  exit 1
}
grep -Fq 'must not include a port' "$embedded_port_log"

invalid_agent_flag_log="$workdir/invalid-agent-flag.log"
invalid_agent_flag_status=0
ALLOW_INSECURE_WEB=1 \
REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED=yes \
  python "$launcher" > /dev/null 2>"$invalid_agent_flag_log" || invalid_agent_flag_status=$?
[[ "$invalid_agent_flag_status" == 2 ]] || {
  echo "ERROR: invalid Antigravity route flag returned $invalid_agent_flag_status instead of 2" >&2
  cat "$invalid_agent_flag_log" >&2
  exit 1
}
grep -Fq 'REMOTE_DEV_LAUNCHER_ANTIGRAVITY_ENABLED must be 0 or 1' "$invalid_agent_flag_log"

echo 'Optional and authenticated launcher, privilege drop and isolated fixed routing tests: OK'
