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
mkdir -p "$scratch"/{baseline,matching,alternate,missing,override,unsafe,fake}
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
  if [[ "$tool" == python ]]; then
    # The system exposes two exact Python versions; the first remains default.
    versions[$tool]="$(sed -nE 's/^python = \["([^"]+)", "[^"]+"\]$/\1/p' /etc/mise/config.toml)"
  else
  versions[$tool]="$(sed -n "s/^$tool = \"\([^\"]*\)\"$/\1/p" /etc/mise/config.toml)"
  fi
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
[[ "$(python3 --version)" == "${outputs[python]}" ]]

# Opting into Python 3.15 must not mutate the globally pinned 3.14 default.
python315_version="$(sed -nE 's/^python = \["[^"]+", "([^"]+)"\]$/\1/p' /etc/mise/config.toml)"
[[ "$python315_version" =~ ^3[.]15[.][0-9]+$ ]]
printf '[tools]\npython = "%s"\n' "$python315_version" > "$scratch/alternate/mise.toml"
cd "$scratch/alternate"
[[ "$(python --version)" == "Python $python315_version" ]]
[[ "$(python3 --version)" == "Python $python315_version" ]]
[[ "$(mise which python)" == /opt/remote-dev/mise/installs/python/"$python315_version"/* ]]
cd "$scratch/matching"
[[ "$(python --version)" == "${outputs[python]}" ]]

# Two offline uv venvs exercise real interpreter selection, independent
# site-packages and no global mutation, in both hardened networkless agent roles.
export UV_CACHE_DIR="$scratch/uv-cache" UV_PYTHON_DOWNLOADS=never
python315_binary="/opt/remote-dev/mise/installs/python/$python315_version/bin/python3.15"
[[ -x "$python315_binary" ]]
venv314="$scratch/venv-314"
venv315="$scratch/venv-315"
if ! uv venv --offline --python "${binaries[python]}" "$venv314" > "$scratch/uv314-output" 2>&1; then
  cat "$scratch/uv314-output" >&2
  echo "ERROR: offline Python 3.14 uv venv creation failed" >&2
  exit 1
fi
if ! uv venv --offline --python "$python315_binary" "$venv315" > "$scratch/uv315-output" 2>&1; then
  cat "$scratch/uv315-output" >&2
  echo "ERROR: offline Python 3.15 uv venv creation failed" >&2
  exit 1
fi
verify_python_venv() {
  local venv="$1" version="$2"
  "$venv/bin/python" - "$version" "$venv" <<'PY'
import pathlib
import sys
import sysconfig

expected = tuple(map(int, sys.argv[1].split(".")))
venv = pathlib.Path(sys.argv[2]).resolve()
assert sys.version_info[:3] == expected, (sys.version, expected)
assert pathlib.Path(sys.prefix).resolve() == venv
assert sys.prefix != sys.base_prefix
assert pathlib.Path(sysconfig.get_path("purelib")).is_relative_to(venv)
PY
}
verify_python_venv "$venv314" "${versions[python]}"
verify_python_venv "$venv315" "$python315_version"
site314="$("$venv314/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
site315="$("$venv315/bin/python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
[[ "$site314" != "$site315" ]]
printf 'VALUE = "only-314"\n' > "$site314/remote_dev_venv_314_probe.py"
printf 'VALUE = "only-315"\n' > "$site315/remote_dev_venv_315_probe.py"
"$venv314/bin/python" -c '
import importlib.util
from remote_dev_venv_314_probe import VALUE
assert VALUE == "only-314"
assert importlib.util.find_spec("remote_dev_venv_315_probe") is None
'
"$venv315/bin/python" -c '
import importlib.util
from remote_dev_venv_315_probe import VALUE
assert VALUE == "only-315"
assert importlib.util.find_spec("remote_dev_venv_314_probe") is None
'
[[ "$(python --version)" == "${outputs[python]}" ]]
[[ "$(python3 --version)" == "${outputs[python]}" ]]
[[ "$(mise which python)" == "${binaries[python]}" ]]
echo "Offline uv venvs (Python ${versions[python]} and $python315_version) are isolated: OK"

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
cd "$scratch/missing"
if python3 --version > "$scratch/error" 2>&1; then
  echo "ERROR: missing project Python unexpectedly allowed python3" >&2
  exit 1
fi
grep -Fq 'Tool not installed for shim' "$scratch/error"
grep -Fq '3.12.1' "$scratch/error"
if grep -Eq 'installing|UNEXPECTED-FALLBACK' "$scratch/error"; then
  cat "$scratch/error" >&2
  exit 1
fi
[[ ! -e "$MISE_STATE_DIR/fallback-marker" ]]
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
