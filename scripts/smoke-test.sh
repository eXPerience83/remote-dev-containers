#!/usr/bin/env bash
set -euo pipefail

if (( $# != 0 && $# != 2 )); then
  echo "Usage: codex-smoke-test [expected-image-version expected-source-revision]" >&2
  exit 2
fi

if [[ ! -r /etc/os-release ]]; then
  echo "MISSING: /etc/os-release" >&2
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
expected_ubuntu="${REMOTE_DEV_UBUNTU_VERSION:-}"
printf 'Base OS: %s %s (expected Ubuntu %s)\n' "${ID:-unknown}" "${VERSION_ID:-unknown}" "${expected_ubuntu:-unset}"
if [[ "${ID:-}" != "ubuntu" || -z "$expected_ubuntu" || "${VERSION_ID:-}" != "$expected_ubuntu" ]]; then
  echo "ERROR: child image is not based on the expected Ubuntu release" >&2
  exit 1
fi

metadata_dir=/usr/share/remote-dev
if ! remote-dev-version --check; then
  echo "ERROR: embedded image metadata is missing or invalid" >&2
  exit 1
fi

image_version="$(<"$metadata_dir/image-version")"
source_revision="$(<"$metadata_dir/source-revision")"
expected_image_version="${1:-$image_version}"
expected_source_revision="${2:-$source_revision}"

if [[ "$image_version" != "$expected_image_version" ]]; then
  echo "ERROR: image version metadata mismatch: expected $expected_image_version, got $image_version" >&2
  exit 1
fi
if [[ "$source_revision" != "$expected_source_revision" ]]; then
  echo "ERROR: source revision metadata mismatch: expected $expected_source_revision, got $source_revision" >&2
  exit 1
fi

default_output="$(remote-dev-version)"
menu_output="$(remote-dev-version --menu)"
short_revision="${source_revision:0:12}"

for expected_line in \
  "Image version: $image_version" \
  "Source revision: $source_revision"; do
  if ! grep -Fxq "$expected_line" <<<"$default_output"; then
    echo "ERROR: remote-dev-version output is missing: $expected_line" >&2
    exit 1
  fi
done
if ! grep -Fxq "Image: $image_version @ $short_revision" <<<"$menu_output"; then
  echo "ERROR: menu metadata does not match the embedded values" >&2
  exit 1
fi

printf '%s\n' "$default_output"
printf '%s\n' "$menu_output"

codex --version
bwrap --version
gh --version | head -n 1
git --version
python --version
node --version
npm --version
uv --version
ttyd --version
tmux -V
mise --version

workdir="$(mktemp -d)"
tmux_socket="remote-dev-smoke-$$"
cleanup() {
  tmux -L "$tmux_socket" kill-server >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT

cd "$workdir"
git init -q
printf 'print("ok")\n' > smoke.py
python smoke.py | grep -Fx ok
node -e 'console.log("ok")' | grep -Fx ok

if [[ "${REMOTE_DEV_SKIP_TMUX_SMOKE:-0}" != "1" ]]; then
  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=fresh-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux

  fresh_name="$(tmux -L "$tmux_socket" display-message -p -t '=fresh-session:' '#{window_name}')"
  if [[ "$fresh_name" != remote-dev ]]; then
    echo "ERROR: fresh tmux session window name is $fresh_name, expected remote-dev" >&2
    exit 1
  fi

  tmux -L "$tmux_socket" new-session -d -s existing-session -n legacy-name 'sleep 30'
  REMOTE_DEV_TMUX_DETACHED=1 \
  TMUX_SOCKET_NAME="$tmux_socket" \
  TMUX_SESSION=existing-session \
  START_MODE=shell \
  WORKSPACE=/workspace \
    /usr/local/bin/attach-remote-dev-tmux

  existing_name="$(tmux -L "$tmux_socket" display-message -p -t '=existing-session:' '#{window_name}')"
  if [[ "$existing_name" != remote-dev ]]; then
    echo "ERROR: existing tmux session window name is $existing_name, expected remote-dev" >&2
    exit 1
  fi

  echo "Tmux fresh and existing session naming: OK"
else
  echo "Tmux runtime smoke test: skipped during image build"
fi
