#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "Usage: $0 <base@digest> <runtime@digest> <source-sha> <edge-version>" >&2
  exit 2
fi

base_ref="$1"
runtime_ref="$2"
expected_revision="$3"
expected_version="$4"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

fail() {
  echo "ERROR: edge publication candidate validation: $*" >&2
  exit 1
}

[[ "$base_ref" =~ ^ghcr\.io/experience83/remote-dev-base@sha256:[0-9a-f]{64}$ ]] \
  || fail "base reference is not the canonical immutable AMD64 repository digest"
[[ "$runtime_ref" =~ ^ghcr\.io/experience83/remote-dev@sha256:[0-9a-f]{64}$ ]] \
  || fail "runtime reference is not the canonical immutable AMD64 repository digest"
[[ "$expected_revision" =~ ^[0-9a-f]{40}$ ]] \
  || fail "expected source revision must be a full lowercase Git SHA"
[[ "$expected_version" =~ ^edge-[0-9]{4}\.[0-9]{2}\.[0-9]{2}-[0-9a-f]{7}$ ]] \
  || fail "expected edge version is malformed"
[[ "${expected_version##*-}" == "${expected_revision:0:7}" ]] \
  || fail "edge version short SHA does not match expected source revision"

for ref in "$base_ref" "$runtime_ref"; do
  docker pull --quiet "$ref" >/dev/null
done

assert_label() {
  local ref="$1"
  local key="$2"
  local expected="$3"
  local actual
  actual="$(docker image inspect "$ref" --format "{{ index .Config.Labels \"$key\" }}")" \
    || fail "could not inspect $key on $ref"
  [[ "$actual" == "$expected" ]] \
    || fail "$ref label $key is '$actual', expected '$expected'"
}

for ref in "$base_ref" "$runtime_ref"; do
  platform="$(docker image inspect "$ref" --format '{{.Os}}/{{.Architecture}}')" \
    || fail "could not inspect platform on $ref"
  [[ "$platform" == linux/amd64 ]] \
    || fail "$ref platform is '$platform', expected 'linux/amd64'"
  assert_label "$ref" org.opencontainers.image.revision "$expected_revision"
  assert_label "$ref" org.opencontainers.image.version "$expected_version"
  assert_label "$ref" io.github.experience83.remote-dev.channel edge
done

# No candidate process executes before immutable reference, platform and labels pass.
# Bundled notices must validate on the exact images that may be promoted.
docker run --rm --entrypoint remote-dev-notices "$base_ref" --check
docker run --rm --entrypoint remote-dev-notices "$runtime_ref" --check

# Exercise the exact runtime candidate rather than rebuilding a second image.
docker run --rm --entrypoint /usr/local/bin/codex-smoke-test "$runtime_ref"
docker run --rm \
  --network none \
  --entrypoint /opt/remote-dev/mise/shims/python \
  -v "$root/scripts/test-remote-dev-context7-runtime-isolation.py:/tmp/test-remote-dev-context7-runtime-isolation.py:ro" \
  -e REMOTE_DEV_CONTEXT7_DEVICE_LOGIN_HELPER=/usr/local/bin/remote-dev-context7-device-login \
  "$runtime_ref" /tmp/test-remote-dev-context7-runtime-isolation.py

timeout --foreground 60s docker run --rm \
  --user 0:0 \
  --network none \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --entrypoint /opt/remote-dev/mise/shims/python \
  -v "$root/scripts/test-codex-runtime-noexec-staging.py:/tmp/test-codex-runtime-noexec-staging.py:ro" \
  -e REMOTE_DEV_CODEX_RUNTIME_MANAGER=/usr/local/bin/remote-dev-codex-runtime \
  "$runtime_ref" /tmp/test-codex-runtime-noexec-staging.py

bash "$root/scripts/runtime-smoke-test.sh" "$runtime_ref"
bash "$root/scripts/test-web-password-runtime.sh" "$runtime_ref"
bash "$root/scripts/test-cross-service-isolation.sh" "$runtime_ref"

echo "Exact edge publication candidate validation: OK"
