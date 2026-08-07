sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

current_uid() {
  id -u
}

resolve_sandbox_identity() {
  if [[ "$(current_uid)" == 0 ]]; then
    sandbox_uid=65534
    sandbox_gid=65534
    sandbox_user=nobody
    sandbox_requires_drop=1
  else
    sandbox_uid="$(id -u)"
    sandbox_gid="$(id -g)"
    sandbox_user="$(id -un)"
    sandbox_requires_drop=0
  fi
}

verify_owned_regular_file() {
  local label="$1"
  local path="$2"
  [[ -f "$path" && ! -L "$path" ]] || fail "$label is missing, not regular, or is a symlink: $path"
  [[ "$(stat -c '%u' "$path")" == "$(current_uid)" ]] \
    || fail "$label is not owned by the current service user: $path"
}

verify_file_bounds() {
  local label="$1"
  local path="$2"
  local maximum="$3"
  local actual_size
  verify_owned_regular_file "$label" "$path"
  actual_size="$(stat -c '%s' "$path")"
  [[ "$actual_size" =~ ^[0-9]+$ && "$actual_size" -gt 0 && "$actual_size" -le "$maximum" ]] \
    || fail "$label size is outside the supported range: $actual_size"
}

verify_file_identity() {
  local label="$1"
  local path="$2"
  local trusted_size="$3"
  local trusted_sha="$4"
  local actual_size actual_sha

  verify_owned_regular_file "$label" "$path"
  actual_size="$(stat -c '%s' "$path")"
  [[ "$actual_size" == "$trusted_size" ]] \
    || fail "$label size differs from its private manifest ($actual_size != $trusted_size)"
  actual_sha="$(sha256_file "$path")"
  [[ "$actual_sha" == "$trusted_sha" ]] || fail "$label SHA-256 differs from its private manifest"
}

owned_regular_file_matches() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" && "$(stat -c '%u' "$path" 2>/dev/null)" == "$(current_uid)" ]]
}

file_identity_matches() {
  local path="$1"
  local trusted_size="$2"
  local trusted_sha="$3"
  owned_regular_file_matches "$path" || return 1
  [[ "$(stat -c '%s' "$path" 2>/dev/null)" == "$trusted_size" ]] || return 1
  [[ "$(sha256_file "$path" 2>/dev/null)" == "$trusted_sha" ]]
}

validate_official_url() {
  local value="$1"
  local base="${2:-}"
  python3 - "$value" "$base" <<'PY'
from __future__ import annotations

import sys
from urllib.parse import urljoin, urlsplit

value, base = sys.argv[1:]
if not value or "\\" in value or any(ord(char) < 0x21 or ord(char) == 0x7F for char in value):
    raise SystemExit(1)
candidate = urljoin(base, value) if base else value
try:
    parsed = urlsplit(candidate)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
valid = (
    parsed.scheme == "https"
    and parsed.hostname == "antigravity.google"
    and port in (None, 443)
    and parsed.username is None
    and parsed.password is None
    and parsed.fragment == ""
)
if not valid:
    raise SystemExit(1)
print(candidate)
PY
}

safe_official_url() {
  validate_official_url "$1" >/dev/null
}

resolve_official_redirect() {
  validate_official_url "$2" "$1"
}

run_bounded() {
  local stdout_path="$1"
  local stderr_path="$2"
  local seconds="$3"
  local file_limit_blocks="$4"
  shift 4
  (
    ulimit -f "$file_limit_blocks"
    timeout --signal=TERM --kill-after=5s "${seconds}s" "$@" \
      </dev/null >"$stdout_path" 2>"$stderr_path"
  )
}

run_unprivileged_bounded() {
  local stdout_path="$1"
  local stderr_path="$2"
  local seconds="$3"
  local working_directory="$4"
  local file_limit_blocks="$5"
  shift 5
  (
    cd -- "$working_directory" || return 1
    if (( sandbox_requires_drop )); then
      run_bounded "$stdout_path" "$stderr_path" "$seconds" "$file_limit_blocks" \
        setpriv \
          --reuid "$sandbox_uid" \
          --regid "$sandbox_gid" \
          --clear-groups \
          --no-new-privs \
          "$@"
    else
      run_bounded "$stdout_path" "$stderr_path" "$seconds" "$file_limit_blocks" "$@"
    fi
  )
}

run_binary_bounded() {
  local candidate="$1"
  local home="$2"
  local stdout_path="$3"
  local stderr_path="$4"
  local execution_user="$5"
  shift 5
  local -a command=(
    env -i
      HOME="$home"
      USER="$execution_user"
      LOGNAME="$execution_user"
      SHELL=/bin/bash
      PATH=/usr/local/bin:/usr/bin:/bin
      LANG=C.UTF-8
      LC_ALL=C.UTF-8
      TERM=xterm-256color
      AGY_CLI_DISABLE_AUTO_UPDATE=true
      CI=1
      "$candidate" "$@"
  )
  if [[ "$execution_user" == "$sandbox_user" ]]; then
    run_unprivileged_bounded \
      "$stdout_path" "$stderr_path" 30 "$home" "$CAPTURE_LIMIT_BLOCKS" \
      "${command[@]}"
  else
    run_bounded \
      "$stdout_path" "$stderr_path" 30 "$CAPTURE_LIMIT_BLOCKS" \
      "${command[@]}"
  fi
}

parse_version_capture() {
  local stdout_path="$1"
  local stderr_path="$2"
  local version
  version="$(awk '
    NF {
      count += 1
      line = $0
    }
    END {
      if (count == 1) print line
      else exit 1
    }
  ' "$stdout_path" "$stderr_path")" || fail "Antigravity version output was not one bounded non-empty line"
  version="$(sed 's/^[[:space:]]*//;s/[[:space:]]*$//' <<<"$version")"
  [[ "$version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] \
    || fail "Antigravity version output is not a supported semantic version"
  printf '%s\n' "$version"
}

inspect_binary_candidate() {
  local candidate="$1"
  local candidate_exec="$2"
  local isolated_home="$3"
  local inspection_dir="$4"
  local readelf_out="$inspection_dir/readelf.out"
  local readelf_err="$inspection_dir/readelf.err"
  local version_out="$inspection_dir/version.out"
  local version_err="$inspection_dir/version.err"
  local help_out="$inspection_dir/help.out"
  local help_err="$inspection_dir/help.err"

  [[ -f "$candidate" && ! -L "$candidate" ]] \
    || fail "installed Antigravity payload is missing, not regular, or is a symlink"
  [[ "$(stat -c '%u' "$candidate")" == "$sandbox_uid" ]] \
    || fail "installed Antigravity payload is not owned by the isolated installer user"
  local candidate_size
  candidate_size="$(stat -c '%s' "$candidate")"
  [[ "$candidate_size" =~ ^[0-9]+$ && "$candidate_size" -gt 0 && "$candidate_size" -le "$MAX_BINARY_SIZE" ]] \
    || fail "installed Antigravity payload size is outside the supported range: $candidate_size"
  chmod 0700 "$candidate"

  run_bounded \
    "$readelf_out" "$readelf_err" 30 "$CAPTURE_LIMIT_BLOCKS" \
    readelf -h "$candidate" \
    || fail "installed Antigravity payload is not a readable ELF executable"
  grep -Eq 'Class:[[:space:]]+ELF64' "$readelf_out" \
    || fail "installed Antigravity payload is not ELF64"
  grep -Eq 'Machine:[[:space:]]+(Advanced Micro Devices X86-64|AMD x86-64)' "$readelf_out" \
    || fail "installed Antigravity payload is not Linux AMD64"

  candidate_binary_size="$(stat -c '%s' "$candidate")"
  candidate_binary_sha="$(sha256_file "$candidate")"
  run_binary_bounded "$candidate_exec" "$isolated_home" "$version_out" "$version_err" "$sandbox_user" --version \
    || fail "installed Antigravity payload failed its bounded version check"
  candidate_version="$(parse_version_capture "$version_out" "$version_err")"
  run_binary_bounded "$candidate_exec" "$isolated_home" "$help_out" "$help_err" "$sandbox_user" --help \
    || fail "installed Antigravity payload failed its bounded help check"
  [[ -s "$help_out" || -s "$help_err" ]] || fail "installed Antigravity payload returned empty help output"

  [[ -f "$candidate" && ! -L "$candidate"
     && "$(stat -c '%u' "$candidate")" == "$sandbox_uid"
     && "$(stat -c '%s' "$candidate")" == "$candidate_binary_size"
     && "$(sha256_file "$candidate")" == "$candidate_binary_sha" ]] \
    || fail "installed Antigravity payload changed during bounded validation"
}
