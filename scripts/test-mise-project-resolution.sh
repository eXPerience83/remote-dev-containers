#!/usr/bin/env bash
set -euo pipefail

# The default path tests the image ENV, for both agents, without network access.
# --local runs the same assertions in an existing Remote Dev environment.
if [[ "${1:-}" != --local ]]; then
  image="${1:-remote-dev:local}"
  for role in codex antigravity; do
    timeout --foreground 60s docker run --rm --network none --read-only \
      --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 64 \
      --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
      --tmpfs /workspace:rw,nosuid,nodev,size=64m,mode=1777 \
      -e TMPDIR=/workspace -e "REMOTE_DEV_ROLE=$role" \
      -v "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/test-mise-project-resolution.sh:/test-mise-project-resolution.sh:ro" \
      --entrypoint /bin/bash "$image" /test-mise-project-resolution.sh --local
  done
  exit 0
fi

: "${TMPDIR:?an executable scratch TMPDIR is required}"
[[ "${MISE_NOT_FOUND_AUTO_INSTALL:-}" == false ]]
[[ "${MISE_NOT_FOUND_SYSTEM_FALLBACK:-}" == false ]]
base_verify="${REMOTE_DEV_BASE_VERIFY:-/usr/local/bin/remote-dev-base-verify}"
base_verify="$(realpath "$base_verify")"
scratch="$(mktemp -d "$TMPDIR/mise-resolution-XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export MISE_STATE_DIR="$scratch/state" MISE_CACHE_DIR="$scratch/cache"
export MISE_CONFIG_DIR="$scratch/config" MISE_GLOBAL_CONFIG_FILE="$scratch/config/config.toml"
unset MISE_TRUSTED_CONFIG_PATHS MISE_TRUSTED_CONFIG_FILES
# Parent processes entered through a shim may have real bin dirs prepended.
# Exercise the actual shim boundary, with a detectable same-name fallback.
export PATH="/opt/remote-dev/mise/shims:$scratch/fake:/usr/local/bin:/usr/bin:/bin"
mkdir -p "$scratch"/{baseline,matching,missing,override,unsafe,fake}
cd "$scratch/baseline"

# The canonical public commands must resolve in the neutral built-image fixture.
# shellcheck source=scripts/common-tool-baseline.sh
source /usr/local/lib/remote-dev/common-tool-baseline.sh
baseline="$(remote_dev_read_common_tool_baseline)"
[[ "$(stat -c '%u:%g %a' /usr/share/remote-dev/common-tool-baseline.txt)" == '0:0 444' ]]
while IFS= read -r cmd; do
  command -v "$cmd" >/dev/null
done <<< "$baseline"

snapshot_store() {
  find /opt/remote-dev/mise -printf '%P %y %s %T@ %C@ %l\n' | LC_ALL=C sort
}
snapshot_store > "$scratch/store-before"
tools=(python node uv)
declare -A versions binaries outputs
for tool in "${tools[@]}"; do
  versions[$tool]="$(sed -n "s/^$tool = \"\([^\"]*\)\"$/\1/p" /etc/mise/config.toml)"
  [[ -n "${versions[$tool]}" ]]
  binaries[$tool]="$(mise which "$tool")"
  [[ "${binaries[$tool]}" == /opt/remote-dev/mise/installs/"$tool"/"${versions[$tool]}"/* ]]
  outputs[$tool]="$("$tool" --version)"
  [[ "${outputs[$tool]}" == *"${versions[$tool]}"* ]]
  printf '%s baseline: %s\n' "$tool" "${outputs[$tool]}"
  printf '%s = "%s"\n' "$tool" "${versions[$tool]}" >> "$scratch/matching/tools"
  sha256sum "${binaries[$tool]}" >> "$scratch/binaries-before"
done
{ printf '[tools]\n'; cat "$scratch/matching/tools"; } > "$scratch/matching/mise.toml"
cd "$scratch/matching"
for tool in "${tools[@]}"; do
  [[ "$(mise which "$tool")" == "${binaries[$tool]}" ]]
  [[ "$("$tool" --version)" == "${outputs[$tool]}" ]]
done
[[ "$(mise settings get auto_install)" == true ]]
[[ "$(mise settings get exec_auto_install)" == true ]]
[[ "$(mise settings get safe)" == false ]]
[[ "$(mise settings get paranoid)" == false ]]
[[ "$(mise exec -- python --version)" == "${outputs[python]}" ]]

# Normal, exact missing declarations for each of the three image-managed tools.
missing_versions=(3.12.1 22.0.0 0.6.0)
for i in "${!tools[@]}"; do
  tool="${tools[$i]}"
  [[ ! -e "/opt/remote-dev/mise/installs/$tool/${missing_versions[$i]}" ]]
  printf '[tools]\n%s = "%s"\n' "$tool" "${missing_versions[$i]}" > "$scratch/missing/mise.toml"
  cat > "$scratch/fake/$tool" <<'FAKE'
#!/bin/bash
printf 'UNEXPECTED-FALLBACK\n'
touch "$MISE_STATE_DIR/fallback-marker"
FAKE
  chmod 0700 "$scratch/fake/$tool"
  cd "$scratch/missing"
  if "$tool" --version > "$scratch/error" 2>&1; then
    echo "ERROR: missing $tool succeeded" >&2; exit 1
  fi
  grep -Fq 'Tool not installed for shim' "$scratch/error"
  grep -Fq "${missing_versions[$i]}" "$scratch/error"
  if grep -Eq 'installing|UNEXPECTED-FALLBACK' "$scratch/error"; then
    cat "$scratch/error" >&2; exit 1
  fi
  [[ ! -e "$MISE_STATE_DIR/fallback-marker" ]]
done
printf '[tools]\npython = "3.12.1"\n' > "$scratch/missing/mise.toml"
printf '[tools]\npython = "3.12.1"\n[settings]\nnot_found_auto_install = true\nnot_found_system_fallback = true\n' > "$scratch/override/mise.toml"
cd "$scratch/override"
# Trust only this synthetic settings fixture, in the isolated state directory.
mise trust >/dev/null
for setting in not_found_auto_install not_found_system_fallback; do
  [[ "$(mise settings get "$setting")" == false ]]
done
if python --version > "$scratch/error" 2>&1; then exit 1; fi
grep -Fq 'Tool not installed for shim' "$scratch/error"
[[ ! -e "$MISE_STATE_DIR/fallback-marker" ]]

cat > "$scratch/unsafe/mise.toml" <<EOF
[tools]
python = "${versions[python]}"
[env]
PROBE = "{{ exec(command='touch $scratch/unsafe-marker') }}"
EOF
cd "$scratch/unsafe"
for tool in "${tools[@]}"; do
  if MISE_STATE_DIR="$scratch/untrusted-$tool" "$tool" --version > "$scratch/error" 2>&1; then exit 1; fi
  grep -Fq 'not trusted' "$scratch/error"
  [[ ! -e "$scratch/unsafe-marker" ]]
done

# Both a missing declaration and executable untrusted config must be irrelevant
# to baseline verification. Compare the complete output with neutral execution.
cd "$scratch/baseline"
bash "$base_verify" > "$scratch/base-expected"
for project in missing unsafe; do
  cd "$scratch/$project"
  bash "$base_verify" > "$scratch/base-actual"
  cmp "$scratch/base-expected" "$scratch/base-actual"
done
[[ ! -e "$scratch/unsafe-marker" ]]
[[ ! -e "$MISE_STATE_DIR/fallback-marker" ]]
snapshot_store > "$scratch/store-after"
cmp "$scratch/store-before" "$scratch/store-after"
sha256sum --check --status "$scratch/binaries-before"
echo "mise project resolution (${REMOTE_DEV_ROLE:-shell}): OK"
