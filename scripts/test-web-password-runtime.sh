#!/usr/bin/env bash
set -euo pipefail

image="${1:-remote-dev:local}"
name="remote-dev-web-password-${RANDOM}-$$"
malformed_name="${name}-malformed"
log_file="$(mktemp)"
secret="synthetic-agent-password-${RANDOM}-$$"

cleanup() {
  docker rm -f "$name" "$malformed_name" >/dev/null 2>&1 || true
  rm -f "$log_file"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# The configured value must be consumed by the startup wrapper rather than
# inherited by ttyd or terminal child processes as a generic environment value.
docker run -d \
  --name "$name" \
  --env "WEB_PASSWORD=$secret" \
  --env WEB_CHECK_ORIGIN=1 \
  --env START_MODE=shell \
  "$image" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$name" pgrep -x ttyd >/dev/null 2>&1; then
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" != true ]]; then
    docker logs "$name" >&2 || true
    fail "authenticated agent stopped before ttyd became ready"
  fi
  sleep 1
done

docker exec "$name" pgrep -x ttyd >/dev/null 2>&1 \
  || fail "authenticated agent did not start ttyd"

if docker exec "$name" sh -c '
  pid="$(pgrep -xo ttyd)"
  tr "\0" "\n" < "/proc/$pid/environ" | grep -q "^WEB_PASSWORD="
'; then
  fail "WEB_PASSWORD remained in the ttyd child-process environment"
fi

status="$(docker exec "$name" curl --silent --output /dev/null --write-out '%{http_code}' \
  --user "codex:$secret" http://127.0.0.1:7681/)" \
  || fail "authenticated ttyd request could not be evaluated"
[[ "$status" == 200 ]] || fail "authenticated ttyd request returned $status"

# A client with valid HTTP Basic auth can send an invalid ttyd AuthToken.
# ttyd 1.7.7 logs the rejected token at WARN level. Exercise that path with
# synthetic data, and ensure it cannot reappear in the container log stream.
docker exec -i "$name" node - "$secret" <<'NODE'
"use strict";
const net = require("node:net");
const crypto = require("node:crypto");

const token = Buffer.from("codex:" + process.argv[2]).toString("base64");
const invalidToken = token + "-invalid";
const socket = net.connect({ host: "127.0.0.1", port: 7681 });
let done = false;
let upgraded = false;
let requestBuffer = Buffer.alloc(0);
const timeout = setTimeout(() => fail("WebSocket auth fixture timed out"), 5000);

function fail(message) {
  if (done) return;
  done = true;
  clearTimeout(timeout);
  socket.destroy();
  console.error(message);
  process.exitCode = 1;
}
function succeed() {
  if (done) return;
  done = true;
  clearTimeout(timeout);
  socket.destroy();
}
function writeMaskedFrame(payload) {
  const data = Buffer.from("0" + JSON.stringify({
    AuthToken: payload, columns: 80, rows: 24,
  }), "utf8");
  const header = data.length < 126
    ? Buffer.from([0x81, 0x80 | data.length])
    : Buffer.from([0x81, 0xfe, data.length >> 8, data.length & 255]);
  const mask = crypto.randomBytes(4);
  const body = Buffer.alloc(data.length);
  for (let i = 0; i < data.length; i++) body[i] = data[i] ^ mask[i % 4];
  socket.write(Buffer.concat([header, mask, body]));
}

socket.on("connect", () => {
  const key = crypto.randomBytes(16).toString("base64");
  socket.write([
    "GET /ws HTTP/1.1",
    "Host: 127.0.0.1:7681",
    "Upgrade: websocket",
    "Connection: Upgrade",
    "Sec-WebSocket-Key: " + key,
    "Sec-WebSocket-Version: 13",
    "Sec-WebSocket-Protocol: tty",
    "Origin: http://127.0.0.1:7681",
    "Authorization: Basic " + token,
    "", "",
  ].join("\r\n"));
});
socket.on("data", data => {
  if (upgraded) return;
  requestBuffer = Buffer.concat([requestBuffer, data]);
  const end = requestBuffer.indexOf("\r\n\r\n");
  if (end < 0) return;
  const headers = requestBuffer.subarray(0, end).toString("utf8");
  if (!headers.startsWith("HTTP/1.1 101") && !headers.startsWith("HTTP/1.0 101")) {
    return fail("WebSocket fixture failed authentication/handshake");
  }
  upgraded = true;
  writeMaskedFrame(invalidToken);
});
socket.on("end", () => {
  if (!upgraded) fail("WebSocket closed before reaching AuthToken check");
  else succeed();
});
socket.on("close", () => {
  if (!done && upgraded) succeed();
  else if (!done) fail("WebSocket closed before upgrade");
});
socket.on("error", error => fail("WebSocket fixture socket error: " + error.code));
NODE

# The server may have buffered its warning before the connection closed.
sleep 1
# ttyd 1.7.7 logs the Base64 credential at NOTICE (bit 4), and the
# rejected AuthToken at WARN (bit 2). Mask 1 retains only ERR (bit 1).
docker logs "$name" >"$log_file" 2>&1
encoded_credential="$(printf 'codex:%s' "$secret" | base64 | tr -d '\n')"
if grep -Fq "$secret" "$log_file" || grep -Fq "$encoded_credential" "$log_file"; then
  fail "ttyd authentication material leaked into container logs"
fi

docker rm -f "$name" >/dev/null

# CR/LF values must fail before ttyd starts, and error output must not echo any
# reusable password material.
for delimiter in newline carriage-return; do
  : >"$log_file"
  if [[ "$delimiter" == newline ]]; then
    malformed_password=$'synthetic-agent-first\nsynthetic-agent-second'
  else
    malformed_password=$'synthetic-agent-first\rsynthetic-agent-second'
  fi

  malformed_status=0
  timeout 15 docker run --rm \
    --name "$malformed_name" \
    --env "WEB_PASSWORD=$malformed_password" \
    "$image" >"$log_file" 2>&1 || malformed_status=$?

  [[ "$malformed_status" != 0 ]] \
    || fail "$delimiter password unexpectedly started an agent terminal"
  [[ "$malformed_status" != 124 ]] \
    || fail "$delimiter password did not fail closed within 15 seconds"
  grep -Fq 'web password must be a single line' "$log_file" \
    || fail "$delimiter password failed for an unexpected reason"
  if grep -Fq 'synthetic-agent-first' "$log_file"; then
    fail "$delimiter password material was echoed to logs"
  fi
done

echo "Agent WEB_PASSWORD consumption and malformed-value rejection: OK"
