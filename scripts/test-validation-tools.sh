#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" != --local ]]; then
  image="${1:-remote-dev:local}"
  for role in codex antigravity; do
    timeout --foreground 120s docker run --rm --network none --read-only \
      --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 128 \
      --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
      --tmpfs /workspace:rw,nosuid,nodev,size=128m,mode=0700 \
      -e TMPDIR=/workspace -e "REMOTE_DEV_ROLE=$role" \
      -v "$(realpath "${BASH_SOURCE[0]}"):/test-validation-tools.sh:ro" \
      --entrypoint /bin/bash "$image" /test-validation-tools.sh --local
  done
  exit 0
fi
scratch="$(mktemp -d "${TMPDIR:?}/validation-tools-XXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
export MISE_STATE_DIR="$scratch/mise-state" MISE_CACHE_DIR="$scratch/mise-cache"
export MISE_GLOBAL_CONFIG_FILE="$scratch/empty.toml" PRE_COMMIT_HOME="$scratch/pre-commit"
export RUFF_CACHE_DIR="$scratch/ruff-cache" UV_CACHE_DIR="$scratch/uv-cache"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
unset MISE_TRUSTED_CONFIG_PATHS MISE_TRUSTED_CONFIG_FILES
export PATH="/opt/remote-dev/mise/shims:/usr/local/bin:/usr/bin:/bin"
mkdir -p "$scratch/neutral" "$scratch/project" "$scratch/untrusted"
cd "$scratch/neutral"
store_snapshot() { find /opt/remote-dev/mise -printf '%P %y %s %T@ %C@ %l\n' | LC_ALL=C sort; }
# Frozen CLI build caches must not become a second bundled package tree in HOME.
[[ ! -e /root/.cache/uv ]]
store_snapshot > "$scratch/store-before"
for command in ruff pytest pre-commit yq shfmt actionlint; do
  version_key="${command^^}"
  version_key="${version_key//-/_}_VERSION"
  expected="$(sed -n "s/^${version_key}=//p" /usr/share/doc/remote-dev/third_party/BUILD-VERSIONS.env)"
  [[ -n "$expected" ]]
  output="$("$command" --version)"
  [[ "$output" == *"$expected"* ]]
done
python315="$(sed -n 's/^PYTHON_315_VERSION=//p' /usr/share/doc/remote-dev/third_party/BUILD-VERSIONS.env)"
printf '[tools]\npython = "%s"\n' "$python315" > "$scratch/project/mise.toml"
cat > "$scratch/untrusted/mise.toml" <<'TOML'
[env]
PROBE = "{{ exec(command='touch SHOULD-NOT-EXIST') }}"
TOML
for cwd in "$scratch/neutral" "$scratch/project"; do
  cd "$cwd"
  printf 'answer: 41\n' | yq '.answer += 1 | .answer' - | grep -Fxq 42
  printf 'if true;then echo ok;fi\n' | shfmt -i 2 > formatted.sh
  shfmt -d -i 2 formatted.sh
  printf 'import os\n' > bad.py
  if ruff check --no-cache --isolated bad.py > "$scratch/ruff.log" 2>&1; then exit 1; fi
  grep -Fq F401 "$scratch/ruff.log"
  printf 'answer=42\n' | ruff format --isolated - | grep -Fxq 'answer = 42'
  cat > test_probe.py <<'PY'
import sys

def test_isolated_cli():
    assert sys.version_info[:2] == (3, 14)
    assert sys.prefix != sys.base_prefix
    assert '/opt/remote-dev/mise/' in sys.prefix
PY
  pytest -q -p no:cacheprovider test_probe.py
  cat > workflow.yml <<'YAML'
name: offline
on: push
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
YAML
  actionlint -pyflakes= workflow.yml
  sed 's/runs-on: ubuntu-latest/runs-on: definitely-invalid/' workflow.yml > invalid.yml
  if actionlint -pyflakes= invalid.yml > "$scratch/actionlint.log" 2>&1; then exit 1; fi
  grep -Fq 'definitely-invalid' "$scratch/actionlint.log"
  git init -q
  cat > .pre-commit-config.yaml <<'YAML'
repos:
  - repo: local
    hooks:
      - id: offline-system
        name: offline system hook
        language: system
        entry: bash -c 'test -f formatted.sh'
        pass_filenames: false
        always_run: true
YAML
  pre-commit validate-config
  pre-commit run --all-files
  # Both global Python runtimes remain free of CLI modules and dependencies.
  for runtime in /opt/remote-dev/mise/installs/python/3.14.*/bin/python3 /opt/remote-dev/mise/installs/python/3.15.*/bin/python3; do
    "$runtime" -I -c 'import importlib.util; assert all(importlib.util.find_spec(n) is None for n in ("pytest", "pre_commit", "ruff", "yaml", "pluggy", "virtualenv"))'
  done
  if [[ "$cwd" == "$scratch/project" ]]; then
    [[ "$(python --version)" == "Python $python315" ]]
    # A real project venv is explicit and takes precedence only when selected.
    uv venv --offline --python "$(mise which python)" .venv
    .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,15)'
    [[ "$(python --version)" == "Python $python315" ]]
  fi
done
# Untrusted executable config cannot execute through lookup of a new Aqua shim.
cd "$scratch/untrusted"
if yq --version > "$scratch/untrusted.log" 2>&1; then exit 1; fi
[[ ! -e SHOULD-NOT-EXIST ]]
store_snapshot > "$scratch/store-after"
cmp "$scratch/store-before" "$scratch/store-after"
echo "Six offline functional tools, Python isolation and project selection (${REMOTE_DEV_ROLE:-shell}): OK"
