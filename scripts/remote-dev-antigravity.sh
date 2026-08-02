#!/usr/bin/env bash
set -euo pipefail

readonly OFFICIAL_INSTALLER_URL="https://antigravity.google/cli/install.sh"
readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh

cleanup_root=""
cleanup() {
  if [[ -n "$cleanup_root" && -d "$cleanup_root" ]]; then
    rm -rf -- "$cleanup_root"
  fi
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

usage() {
  cat <<'EOF'
Usage: remote-dev-antigravity <install|update|status|path> [--yes] [--menu]

Commands:
  install   Install the reviewed official Antigravity CLI package.
  update    Replace a trusted older installation with the reviewed package.
  status    Report whether the reviewed executable is installed and valid.
  path      Print the canonical executable path.

Normal startup never downloads or updates Antigravity.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

recovery_hint() {
  printf 'Remove %s and %s, then run remote-dev-install-antigravity.\n' "$binary" "$manifest" >&2
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

  [[ "$evidence" == "$ANTIGRAVITY_EVIDENCE" ]] || fail "production evidence path changed"
  [[ "$bin_dir" == "$ANTIGRAVITY_BIN_DIR" ]] || fail "production binary directory changed"
  [[ "$state_dir" == "$ANTIGRAVITY_STATE_DIR" ]] || fail "production state directory changed"
  [[ "$vendor_state_dir" == "$ANTIGRAVITY_VENDOR_STATE_DIR" ]] || fail "production vendor state directory changed"
  [[ "$binary" == "$ANTIGRAVITY_BINARY" ]] || fail "production binary path changed"
  [[ "$manifest" == "$ANTIGRAVITY_MANIFEST" ]] || fail "production manifest path changed"

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
  local tool
  for tool in bash curl jq sha256sum stat mktemp install mv date awk sed dirname env timeout cp rm mkdir chmod; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command is missing: $tool"
  done
}

load_evidence() {
  [[ -r "$evidence" ]] || fail "Antigravity inspection evidence is not readable: $evidence"
  jq -e '(.schema_version | type == "number") and .schema_version >= 2
         and (.blocking_findings | type == "array") and .blocking_findings == []' \
    "$evidence" >/dev/null || fail "Antigravity inspection evidence is invalid"

  expected_installer_url="$(jq -er '.installer.official_url' "$evidence")"
  expected_installer_sha="$(jq -er '.installer.sha256' "$evidence")"
  expected_installer_size="$(jq -er '.installer.size' "$evidence")"
  expected_binary_sha="$(jq -er '.installed_binary.sha256' "$evidence")"
  expected_binary_size="$(jq -er '.installed_binary.size' "$evidence")"
  expected_version="$(jq -er '.installed_binary.version' "$evidence")"

  [[ "$expected_installer_url" == "$OFFICIAL_INSTALLER_URL" ]] \
    || fail "inspection evidence does not reference the fixed official installer URL"
  [[ "$expected_installer_sha" =~ ^[0-9a-f]{64}$ ]] || fail "invalid installer SHA-256 in evidence"
  [[ "$expected_binary_sha" =~ ^[0-9a-f]{64}$ ]] || fail "invalid binary SHA-256 in evidence"
  [[ "$expected_installer_size" =~ ^[0-9]+$ ]] || fail "invalid installer size in evidence"
  [[ "$expected_binary_size" =~ ^[0-9]+$ ]] || fail "invalid binary size in evidence"
  [[ "$expected_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] \
    || fail "invalid Antigravity version in evidence"
}

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

verify_regular_file() {
  local label="$1"
  local path="$2"
  [[ -f "$path" && ! -L "$path" ]] || fail "$label is missing, not regular, or is a symlink: $path"
}

verify_file_identity() {
  local label="$1"
  local path="$2"
  local trusted_size="$3"
  local trusted_sha="$4"
  local actual_size actual_sha

  verify_regular_file "$label" "$path"
  actual_size="$(stat -c '%s' "$path")"
  [[ "$actual_size" == "$trusted_size" ]] \
    || fail "$label size differs from trusted metadata ($actual_size != $trusted_size)"
  actual_sha="$(sha256_file "$path")"
  [[ "$actual_sha" == "$trusted_sha" ]] || fail "$label SHA-256 differs from trusted metadata"
}

run_binary_no_update() {
  local candidate="$1"
  shift
  timeout --signal=TERM --kill-after=5s 30s \
    env HOME="${HOME:-/root}" AGY_CLI_DISABLE_AUTO_UPDATE=true "$candidate" "$@" \
    </dev/null
}

read_version_with_identity() {
  local candidate="$1"
  local trusted_size="$2"
  local trusted_sha="$3"
  local trusted_version="$4"
  local output version

  verify_file_identity "Antigravity executable" "$candidate" "$trusted_size" "$trusted_sha"
  output="$(run_binary_no_update "$candidate" --version 2>/dev/null)" \
    || fail "trusted Antigravity executable failed its bounded version check"
  version="$(printf '%s\n' "$output" | sed -n '1{s/^[[:space:]]*//;s/[[:space:]]*$//;p;}')"
  [[ "$version" == "$trusted_version" ]] || fail "Antigravity version output differs from trusted metadata"
  printf '%s\n' "$version"
}

manifest_matches_target() {
  [[ -r "$manifest" ]] || return 1
  jq -e \
    --arg version "$expected_version" \
    --arg binary_sha "$expected_binary_sha" \
    --argjson binary_size "$expected_binary_size" \
    '.schema_version == 1
     and .runtime_installed == true
     and .bundled_in_image == false
     and .version == $version
     and .binary_sha256 == $binary_sha
     and .binary_size == $binary_size' \
    "$manifest" >/dev/null 2>&1
}

write_manifest() {
  local destination="$1"
  local installed_at
  installed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  jq -n \
    --arg installed_at "$installed_at" \
    --arg version "$expected_version" \
    --arg installer_url "$OFFICIAL_INSTALLER_URL" \
    --arg installer_sha256 "$expected_installer_sha" \
    --arg binary_sha256 "$expected_binary_sha" \
    --argjson binary_size "$expected_binary_size" \
    '{
      schema_version: 1,
      installed_at_utc: $installed_at,
      version: $version,
      installer_url: $installer_url,
      installer_sha256: $installer_sha256,
      binary_sha256: $binary_sha256,
      binary_size: $binary_size,
      runtime_installed: true,
      bundled_in_image: false
    }' >"$destination"
  chmod 0600 "$destination"
}

repair_target_manifest() {
  umask 077
  install -d -m 0700 "$state_dir"
  local repaired="$state_dir/.install.json.repair.$$"
  write_manifest "$repaired"
  mv -f -- "$repaired" "$manifest"
}

read_current_installation() {
  verify_regular_file "existing Antigravity executable" "$binary"

  local actual_sha actual_size
  actual_sha="$(sha256_file "$binary")"
  actual_size="$(stat -c '%s' "$binary")"

  if [[ "$actual_sha" == "$expected_binary_sha" && "$actual_size" == "$expected_binary_size" ]]; then
    current_version="$(read_version_with_identity "$binary" "$expected_binary_size" "$expected_binary_sha" "$expected_version")"
    current_matches_target=1
    if ! manifest_matches_target; then
      repair_target_manifest || {
        echo "ERROR: reviewed executable is valid but its local install manifest could not be repaired" >&2
        recovery_hint
        exit 1
      }
    fi
    return 0
  fi

  if [[ ! -r "$manifest" ]]; then
    echo "ERROR: existing Antigravity executable does not match current evidence and has no trusted install manifest" >&2
    recovery_hint
    exit 1
  fi
  jq -e '.schema_version == 1 and .runtime_installed == true and .bundled_in_image == false' "$manifest" >/dev/null \
    || {
      echo "ERROR: existing Antigravity install manifest is invalid" >&2
      recovery_hint
      exit 1
    }

  local old_sha old_size old_version
  old_sha="$(jq -er '.binary_sha256' "$manifest")"
  old_size="$(jq -er '.binary_size' "$manifest")"
  old_version="$(jq -er '.version' "$manifest")"
  [[ "$old_sha" =~ ^[0-9a-f]{64}$ ]] || { echo "ERROR: existing manifest has an invalid SHA-256" >&2; recovery_hint; exit 1; }
  [[ "$old_size" =~ ^[0-9]+$ ]] || { echo "ERROR: existing manifest has an invalid binary size" >&2; recovery_hint; exit 1; }
  [[ "$old_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] \
    || { echo "ERROR: existing manifest has an invalid version" >&2; recovery_hint; exit 1; }

  if ! current_version="$(read_version_with_identity "$binary" "$old_size" "$old_sha" "$old_version")"; then
    recovery_hint
    exit 1
  fi
  current_matches_target=0
}

show_vendor_disclosure() {
  cat <<EOF
Antigravity is a Google product and is not distributed by Remote Dev.
The reviewed installer will be downloaded directly from:
  $OFFICIAL_INSTALLER_URL
A Google account is required for authenticated use.
Google's separate terms and privacy policy apply:
  https://antigravity.google/terms
  https://policies.google.com/privacy
Remote Dev is not affiliated with or endorsed by Google.
Target reviewed version: $expected_version
EOF
}

confirm_vendor_download() {
  local action="$1"
  local assume_yes="$2"
  show_vendor_disclosure
  if [[ "$assume_yes" == 1 ]]; then
    return 0
  fi

  local answer=""
  [[ -t 0 ]] || fail "$action requires an interactive confirmation or the explicit --yes option"
  read -r -p "Continue with $action? [y/N] " answer

  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Cancelled; no download or installation was performed."; exit 0 ;;
  esac
}

download_installer() {
  local destination="$1"
  curl \
    --proto '=https' \
    --proto-redir '=https' \
    --tlsv1.2 \
    --fail \
    --silent \
    --show-error \
    --location \
    --retry 3 \
    --retry-all-errors \
    --connect-timeout 10 \
    --max-time 300 \
    "$OFFICIAL_INSTALLER_URL" \
    --output "$destination"
  chmod 0700 "$destination"
  verify_file_identity "Antigravity installer" "$destination" "$expected_installer_size" "$expected_installer_sha"
  /bin/bash -n "$destination" || fail "reviewed Antigravity installer is not valid Bash"
}

run_installer_isolated() {
  local installer_path="$1"
  local isolated_home="$2"
  local stage_bin="$3"
  timeout --signal=TERM --kill-after=10s 900s \
    env -i \
      HOME="$isolated_home" \
      USER=root \
      LOGNAME=root \
      SHELL=/bin/bash \
      PATH=/usr/local/bin:/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      TERM=xterm-256color \
      XDG_CACHE_HOME="$isolated_home/.cache" \
      XDG_CONFIG_HOME="$isolated_home/.config" \
      XDG_DATA_HOME="$isolated_home/.local/share" \
      CI=1 \
      /bin/bash "$installer_path" --dir "$stage_bin" \
    </dev/null
}

restore_previous_installation() {
  local had_old_binary="$1"
  local old_binary_backup="$2"
  local had_old_manifest="$3"
  local old_manifest_backup="$4"
  local restore_status=0

  if [[ "$had_old_binary" == 1 ]]; then
    install -m 0700 "$old_binary_backup" "$binary" || restore_status=1
  else
    rm -f -- "$binary" || restore_status=1
  fi
  if [[ "$had_old_manifest" == 1 ]]; then
    install -m 0600 "$old_manifest_backup" "$manifest" || restore_status=1
  else
    rm -f -- "$manifest" || restore_status=1
  fi
  return "$restore_status"
}

publish_verified_install() {
  local staged_binary="$1"
  local staged_manifest="$2"
  local final_new="$bin_dir/.agy.new.$$"
  local manifest_new="$state_dir/.install.json.new.$$"
  local old_binary_backup="$cleanup_root/previous-agy"
  local old_manifest_backup="$cleanup_root/previous-install.json"
  local had_old_binary=0 had_old_manifest=0

  if [[ -f "$binary" && ! -L "$binary" ]]; then
    install -m 0700 "$binary" "$old_binary_backup"
    had_old_binary=1
  fi
  if [[ -f "$manifest" && ! -L "$manifest" ]]; then
    install -m 0600 "$manifest" "$old_manifest_backup"
    had_old_manifest=1
  fi

  install -m 0700 "$staged_binary" "$final_new"
  install -m 0600 "$staged_manifest" "$manifest_new"
  mv -f -- "$final_new" "$binary"
  if ! mv -f -- "$manifest_new" "$manifest"; then
    if ! restore_previous_installation "$had_old_binary" "$old_binary_backup" "$had_old_manifest" "$old_manifest_backup"; then
      echo "ERROR: publishing the manifest failed and the previous installation could not be fully restored" >&2
      recovery_hint
      exit 1
    fi
    fail "publishing the Antigravity manifest failed; the previous installation was restored"
  fi
}

install_or_update() {
  local action="$1"
  local assume_yes="$2"
  local current_version="not installed"
  local current_matches_target=0

  require_supported_platform
  require_tools
  load_evidence

  local binary_present=0
  if [[ -e "$binary" || -L "$binary" ]]; then
    binary_present=1
  fi

  case "$action" in
    install)
      (( binary_present == 0 )) || fail "Antigravity is already installed at $binary; use update"
      ;;
    update)
      (( binary_present == 1 )) || fail "Antigravity is not installed; use install"
      read_current_installation
      if (( current_matches_target == 1 )); then
        echo "Antigravity $current_version is already the reviewed version; no download was needed."
        return 0
      fi
      ;;
    *) fail "internal unsupported action: $action" ;;
  esac

  confirm_vendor_download "$action" "$assume_yes"

  cleanup_root="$(mktemp -d "${TMPDIR:-/tmp}/remote-dev-antigravity.XXXXXXXX")"
  local installer_path="$cleanup_root/install.sh"
  local isolated_home="$cleanup_root/home"
  local stage_bin="$cleanup_root/bin"
  local staged_binary="$stage_bin/agy"
  local staged_manifest="$cleanup_root/install.json"
  mkdir -m 0700 -p "$isolated_home" "$stage_bin"

  download_installer "$installer_path"
  run_installer_isolated "$installer_path" "$isolated_home" "$stage_bin" \
    || fail "reviewed Antigravity installer failed or exceeded its time limit"

  verify_file_identity "installed Antigravity payload" "$staged_binary" "$expected_binary_size" "$expected_binary_sha"
  chmod 0700 "$staged_binary"
  read_version_with_identity "$staged_binary" "$expected_binary_size" "$expected_binary_sha" "$expected_version" >/dev/null
  write_manifest "$staged_manifest"

  umask 077
  install -d -m 0700 "$bin_dir" "$state_dir" "$vendor_state_dir"
  publish_verified_install "$staged_binary" "$staged_manifest"

  if [[ "$action" == update ]]; then
    echo "Antigravity updated: $current_version -> $expected_version"
  else
    echo "Antigravity $expected_version installed from the reviewed Google package."
  fi
  echo "Executable: $binary"
  echo "Automatic CLI updates remain disabled during Remote Dev launches."
}

status_command() {
  local menu="$1"
  require_tools
  load_evidence
  if [[ ! -e "$binary" && ! -L "$binary" ]]; then
    if [[ "$menu" == 1 ]]; then
      echo "Antigravity: not installed"
    else
      echo "not installed"
    fi
    return 0
  fi

  local current_version="" current_matches_target=0
  read_current_installation
  if (( current_matches_target == 0 )); then
    if [[ "$menu" == 1 ]]; then
      echo "Antigravity: $current_version (update to reviewed $expected_version required)"
    else
      echo "installed version $current_version requires update to reviewed $expected_version"
    fi
    return 3
  fi

  if [[ "$menu" == 1 ]]; then
    echo "Antigravity: $current_version (runtime installed)"
  else
    echo "$current_version"
  fi
}

main() {
  local command="${1:-}"
  [[ -n "$command" ]] || { usage >&2; exit 2; }
  shift || true

  require_antigravity_role

  local assume_yes=0 menu=0
  while (( $# )); do
    case "$1" in
      --yes) assume_yes=1 ;;
      --menu) menu=1 ;;
      -h|--help) usage; exit 0 ;;
      *) fail "unsupported argument: $1" ;;
    esac
    shift
  done

  resolve_paths
  validate_paths

  case "$command" in
    install) install_or_update install "$assume_yes" ;;
    update) install_or_update update "$assume_yes" ;;
    status) status_command "$menu" ;;
    path) printf '%s\n' "$binary" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
