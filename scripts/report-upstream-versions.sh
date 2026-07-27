#!/usr/bin/env bash
set -euo pipefail

source versions.env

release_sha256() {
  local repo="$1"
  local tag="$2"
  local asset="$3"
  gh api "repos/${repo}/releases/tags/${tag}" \
    --jq ".assets[] | select(.name == \"${asset}\") | .digest" \
    | sed 's/^sha256://'
}

latest_codex="$(gh api repos/openai/codex/releases/latest --jq .tag_name)"
latest_gh="$(gh api repos/cli/cli/releases/latest --jq '.tag_name | ltrimstr("v")')"
latest_ttyd="$(gh api repos/tsl0922/ttyd/releases/latest --jq .tag_name)"
latest_mise="$(gh api repos/jdx/mise/releases/latest --jq '.tag_name | ltrimstr("v")')"
latest_uv="$(gh api repos/astral-sh/uv/releases/latest --jq .tag_name)"
latest_python="$(curl -fsSL https://www.python.org/ftp/python/ \
  | grep -oE 'href="3\.14\.[0-9]+/' \
  | sed -E 's/^href="//; s|/$||' \
  | sort -V \
  | tail -n 1)"
latest_node_lts="$(curl -fsSL https://nodejs.org/dist/index.json \
  | jq -r '[.[] | select(.lts != false) | .version | ltrimstr("v")] | first')"
latest_npm="$(curl -fsSL https://registry.npmjs.org/-/package/npm/dist-tags | jq -r .latest)"

printf 'CURRENT_CODEX=%s\nLATEST_CODEX=%s\n' "$CODEX_RELEASE_TAG" "$latest_codex"
printf 'CURRENT_GH=%s\nLATEST_GH=%s\n' "$GH_VERSION" "$latest_gh"
printf 'CURRENT_TTYD=%s\nLATEST_TTYD=%s\n' "$TTYD_VERSION" "$latest_ttyd"
printf 'CURRENT_MISE=%s\nLATEST_MISE=%s\n' "$MISE_VERSION" "$latest_mise"
printf 'CURRENT_PYTHON=%s\nLATEST_PYTHON=%s\n' "$PYTHON_VERSION" "$latest_python"
printf 'CURRENT_NODE=%s\nLATEST_NODE_LTS=%s\n' "$NODE_VERSION" "$latest_node_lts"
printf 'CURRENT_NPM=%s\nLATEST_NPM=%s\n' "$NPM_VERSION" "$latest_npm"
printf 'CURRENT_UV=%s\nLATEST_UV=%s\n' "$UV_VERSION" "$latest_uv"

printf 'CODEX_AMD64_SHA256=%s\n' "$(release_sha256 openai/codex "$latest_codex" codex-x86_64-unknown-linux-musl.tar.gz)"
printf 'CODEX_ARM64_SHA256=%s\n' "$(release_sha256 openai/codex "$latest_codex" codex-aarch64-unknown-linux-musl.tar.gz)"
printf 'GH_AMD64_SHA256=%s\n' "$(release_sha256 cli/cli "v${latest_gh}" "gh_${latest_gh}_linux_amd64.tar.gz")"
printf 'GH_ARM64_SHA256=%s\n' "$(release_sha256 cli/cli "v${latest_gh}" "gh_${latest_gh}_linux_arm64.tar.gz")"
printf 'TTYD_AMD64_SHA256=%s\n' "$(release_sha256 tsl0922/ttyd "$latest_ttyd" ttyd.x86_64)"
printf 'TTYD_ARM64_SHA256=%s\n' "$(release_sha256 tsl0922/ttyd "$latest_ttyd" ttyd.aarch64)"
printf 'MISE_AMD64_SHA256=%s\n' "$(release_sha256 jdx/mise "v${latest_mise}" "mise-v${latest_mise}-linux-x64")"
printf 'MISE_ARM64_SHA256=%s\n' "$(release_sha256 jdx/mise "v${latest_mise}" "mise-v${latest_mise}-linux-arm64")"
