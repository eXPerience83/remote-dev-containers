cleanup() {
  if (( publish_in_progress )); then
    if ! restore_previous_installation \
      "$publish_had_old_binary" "$publish_old_binary_backup" \
      "$publish_had_old_manifest" "$publish_old_manifest_backup"; then
      echo "ERROR: interrupted Antigravity publication could not restore the previous installation" >&2
    fi
    publish_in_progress=0
  fi
  if [[ -n "$cleanup_root" && -d "$cleanup_root" ]]; then
    rm -rf -- "$cleanup_root"
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

usage() {
  cat <<'USAGE'
Usage: remote-dev-antigravity <install|update|status|verify|path> [--yes] [--menu]

Commands:
  install   Install the current compatible Antigravity CLI from Google's official installer.
  update    Explicitly replace the current installation with the current compatible official package.
  status    Inspect local executable/manifest structure and report its review state.
  verify    Fully verify the local executable against its private manifest.
  path      Print the canonical executable path.

Normal startup never downloads or updates Antigravity. Compatible official-source
versions may run while Remote Dev review evidence is pending.
USAGE
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_antigravity_role() {
  [[ -f "$runtime_lib" && -r "$runtime_lib" && ! -L "$runtime_lib" ]] \
    || fail "Remote Dev role definitions are unavailable: $runtime_lib"
  # shellcheck source=/usr/local/lib/remote-dev/remote-dev-runtime.sh
  source "$runtime_lib"

  local resolved_role=""
  resolved_role="$(remote_dev_resolve_role)" || exit $?
  if [[ "$resolved_role" != antigravity ]]; then
    echo "ERROR: Antigravity runtime operations require the gated REMOTE_DEV_ROLE=antigravity service" >&2
    exit 2
  fi
  export REMOTE_DEV_ROLE="$resolved_role"
}

load_canonical_paths() {
  [[ -f "$paths_lib" && -r "$paths_lib" && ! -L "$paths_lib" ]] \
    || fail "canonical Antigravity path definitions are unavailable: $paths_lib"
  # shellcheck source=/usr/local/lib/remote-dev/antigravity-paths.sh
  source "$paths_lib"
}

resolve_paths() {
  load_canonical_paths
  evidence="$ANTIGRAVITY_EVIDENCE"
  bin_dir="$ANTIGRAVITY_BIN_DIR"
  state_dir="$ANTIGRAVITY_STATE_DIR"
  vendor_state_dir="$ANTIGRAVITY_VENDOR_STATE_DIR"
  binary="$ANTIGRAVITY_BINARY"
  manifest="$ANTIGRAVITY_MANIFEST"
}

require_absolute_safe_path() {
  local label="$1"
  local value="$2"
  [[ "$value" == /* && "$value" != //* ]] || fail "$label must be a normalized absolute path"
  case "$value" in
    /|/root|/root/.local|/root/.local/share|/root/.gemini|/workspace|/home|/opt|/usr|/usr/local|/etc|/var|/tmp)
      fail "$label is too broad: $value"
      ;;
  esac
  [[ "$value" != *'/../'* && "$value" != */.. && "$value" != *$'\n'* ]] \
    || fail "$label contains an unsafe path component"
}

reject_symlink_components() {
  local current="$1"
  local previous=""
  while [[ "$current" != / && "$current" != "$previous" ]]; do
    if [[ -L "$current" ]]; then
      fail "refusing symlinked Antigravity path component: $current"
    fi
    previous="$current"
    current="$(dirname "$current")"
  done
  [[ "$current" == / ]] || fail "could not safely resolve path ancestors"
}

validate_paths() {
  require_absolute_safe_path "evidence path" "$evidence"
  require_absolute_safe_path "binary directory" "$bin_dir"
  require_absolute_safe_path "state directory" "$state_dir"
  require_absolute_safe_path "vendor state directory" "$vendor_state_dir"
  require_absolute_safe_path "binary path" "$binary"
  require_absolute_safe_path "manifest path" "$manifest"

  reject_symlink_components "$bin_dir"
  reject_symlink_components "$state_dir"
  reject_symlink_components "$vendor_state_dir"
}

require_supported_platform() {
  [[ "$(uname -s)" == Linux ]] || fail "Antigravity runtime installation currently supports Linux only"
  case "$(uname -m)" in
    x86_64|amd64) ;;
    *) fail "Antigravity runtime installation currently supports Linux AMD64 only" ;;
  esac
}

require_tools() {
  local tool resolved
  for tool in "${ANTIGRAVITY_RUNTIME_TOOLS[@]}"; do
    resolved="$(builtin type -P "$tool" 2>/dev/null)" \
      || fail "required command is missing: $tool"
    [[ -f "$resolved" && -x "$resolved" ]] \
      || fail "required command is not an executable file: $tool ($resolved)"
  done
}

load_evidence() {
  [[ -r "$evidence" ]] || fail "Antigravity inspection evidence is not readable: $evidence"
  jq -e '(.schema_version | type == "number") and .schema_version >= 2
         and (.blocking_findings | type == "array") and .blocking_findings == []' \
    "$evidence" >/dev/null || fail "Antigravity inspection evidence is invalid"

  reviewed_installer_url="$(jq -er '.installer.official_url' "$evidence")"
  reviewed_installer_sha="$(jq -er '.installer.sha256' "$evidence")"
  reviewed_installer_size="$(jq -er '.installer.size' "$evidence")"
  reviewed_binary_sha="$(jq -er '.installed_binary.sha256' "$evidence")"
  reviewed_binary_size="$(jq -er '.installed_binary.size' "$evidence")"
  reviewed_version="$(jq -er '.installed_binary.version' "$evidence")"

  [[ "$reviewed_installer_url" == "$OFFICIAL_INSTALLER_URL" ]] \
    || fail "inspection evidence does not reference the fixed official installer URL"
  [[ "$reviewed_installer_sha" =~ ^[0-9a-f]{64}$ ]] || fail "invalid installer SHA-256 in evidence"
  [[ "$reviewed_binary_sha" =~ ^[0-9a-f]{64}$ ]] || fail "invalid binary SHA-256 in evidence"
  [[ "$reviewed_installer_size" =~ ^[0-9]+$ ]] || fail "invalid installer size in evidence"
  [[ "$reviewed_binary_size" =~ ^[0-9]+$ ]] || fail "invalid binary size in evidence"
  [[ "$reviewed_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] \
    || fail "invalid Antigravity version in evidence"
}
