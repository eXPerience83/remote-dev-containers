#!/usr/bin/env bash
set -euo pipefail

launcher="${REMOTE_DEV_LAUNCHER:-/usr/local/bin/remote-dev-launcher}"
workdir="$(mktemp -d)"
log_file="$workdir/launcher.log"
password_file="$workdir/password"
starting_uid="$(id -u)"
port="$(python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
)"
base_url="http://127.0.0.1:${port}"
secret='synthetic-launcher-secret'
launcher_pid=''

cleanup() {
  if [[ -n "$launcher_pid" ]]; then
    kill "$launcher_pid" >/dev/null 2>&1 || true
    wait "$launcher_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$workdir"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' "$secret" > "$password_file"

WEB_BIND=127.0.0.1 \
WEB_PORT="$port" \
WEB_BASE_PATH=/launcher \
WEB_USERNAME=remote-dev \
WEB_PASSWORD_FILE="$password_file" \
WEB_CHECK_ORIGIN=1 \
ALLOW_INSECURE_WEB=0 \
REMOTE_DEV_LAUNCHER_CODEX_PORT=8765 \
REMOTE_DEV_LAUNCHER_CODEX_PATH=/codex \
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

echo 'Authenticated launcher, privilege drop and fixed routing tests: OK'
