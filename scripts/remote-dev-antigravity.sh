#!/usr/bin/env bash
set -euo pipefail

readonly OFFICIAL_INSTALLER_URL="https://antigravity.google/cli/install.sh"
readonly DEFAULT_EVIDENCE=/usr/share/doc/remote-dev/third_party/antigravity-cli-inspection.json
readonly DEFAULT_BIN_DIR=/root/.local/bin
readonly DEFAULT_STATE_DIR=/root/.local/share/remote-dev/antigravity
readonly DEFAULT_VENDOR_STATE_DIR=/root/.gemini/antigravity-cli

usage() {
  cat <<'EOF'
Usage: remote-dev-antigravity <install|update|status|path> [--yes] [--menu]

Commands:
  install   Install the reviewed official Antigravity CLI package.
  update    Replace an existing installation with the reviewed package.
  status    Report whether the reviewed executable is installed and valid.
  path      Print the canonical executable path.

Normal startup never downloads or updates Antigravity.
EOF
}

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

is_testing() {
  [[ "${REMOTE_DEV_ANTIGRAVITY_TESTING:-0}" == "1" ]]
}

resolve_paths() {
  if is_testing; then
    evidence="${REMOTE_DEV_ANTIGRAVITY_EVIDENCE:?test evidence path is required}"
    bin_dir="${REMOTE_DEV_ANTIGRAVITY_BIN_DIR:?test binary directory is required}"
    state_dir="${REMOTE_DEV_ANTIGRAVITY_STATE_DIR:?test state directory is required}"
    vendor_state_dir="${REMOTE_DEV_ANTIGRAVITY_VENDOR_STATE_DIR:?test vendor state directory is required}"
  else
    evidence="$DEFAULT_EVIDENCE"
    bin_dir="$DEFAULT_BIN_DIR"
    state_dir="$DEFAULT_STATE_DIR"
    vendor_state_dir="$DEFAULT_VENDOR_STATE_DIR"
  fi
  binary="$bin_dir/agy"
  manifest="$state_dir/install.json"
}

require_absolute_safe_path() {
  local label="$1"
  local value="$2"
  [[ "$value" == /* ]] || fail "$label must be an absolute path"
  case "$value" in
    /|/root|/root/.local|/root/.gemini|/workspace)
      fail "$label is too broad: $value"
      ;;
  esac
  [[ "$value" != *'/../'* && "$value" != */.. && "$value" != *$'\n'* ]] \
    || fail "$label contains an unsafe path component"
}

validate_paths() {
  require_absolute_safe_path "evidence path" "$evidence"
  require_absolute_safe_path "binary directory" "$bin_dir"
  require_absolute_safe_path "state directory" "$state_dir"
  require_absolute_safe_path "vendor state directory" "$vendor_state_dir"

  if ! is_testing; then
    [[ "$evidence" == "$DEFAULT_EVIDENCE" ]] || fail "production evidence path changed"
    [[ "$bin_dir" == "$DEFAULT_BIN_DIR" ]] || fail "production binary directory changed"
    [[ "$state_dir" == "$DEFAULT_STATE_DIR" ]] || fail "production state directory changed"
    [[ "$vendor_state_dir" == "$DEFAULT_VENDOR_STATE_DIR" ]] || fail "production vendor state directory changed"
  fi
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
  for tool in bash curl jq sha256sum stat mktemp install mv date; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command is missing: $tool"
  done
}

load_evidence() {
  [[ -r "$evidence" ]] || fail "Antigravity inspection evidence is not readable: $evidence"
  jq -e '.schema_version >= 2 and .blocking_findings == []' "$evidence" >/dev/null \
    || fail "Antigravity inspection evidence is invalid"

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
  local expected_size="$3"
  local expected_sha="$4"
  local actual_size actual_sha

  verify_regular_file "$label" "$path"
  actual_size="$(stat -c '%s' "$path")"
  [[ "$actual_size" == "$expected_size" ]] \
    || fail "$label size differs from reviewed evidence ($actual_size != $expected_size)"
  actual_sha="$(sha256_file "$path")"
  [[ "$actual_sha" == "$expected_sha" ]] \
    || fail "$label SHA-256 differs from reviewed evidence"
}

minimal_installer_env() {
  local isolated_home="$1"
  shift
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
    "$@"
}

run_verified_binary() {
  local candidate="$1"
  shift
  env \
    HOME="${HOME:-/root}" \
    AGY_CLI_DISABLE_AUTO_UPDATE=true \
    "$candidate" "$@"
}

read_verified_version() {
  local candidate="$1"
  local output version

  verify_file_identity "Antigravity executable" "$candidate" "$expected_binary_size" "$expected_binary_sha"
  output="$(run_verified_binary "$candidate" --version 2>/dev/null)" \
    || fail "reviewed Antigravity executable failed its version check"
  version="$(printf '%s\n' "$output" | sed -n '1{s/^[[:space:]]*//;s/[[:space:]]*$//;p;}')"
  [[ "$version" == "$expected_version" ]] \
    || fail "Antigravity version output differs from reviewed evidence"
  printf '%s\n' "$version"
}

confirm_vendor_download() {
  local action="$1"
  local assume_yes="$2"
  if [[ "$assume_yes" == 1 ]]; then
    return 0
  fi
  [[ -t 0 ]] || fail "$action requires an interactive confirmation or the explicit --yes option"

  cat <<EOF
Antigravity is a Google product and is not distributed by Remote Dev.
The reviewed installer will be downloaded directly from:
  $OFFICIAL_INSTALLER_URL
Google's separate terms and privacy disclosures apply.
Remote Dev is not affiliated with or endorsed by Google.

Target reviewed version: $expected_version
EOF
  read -r -p "Continue with $action? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *)
      echo "Cancelled; no download or installation was performed."
      exit 0
      ;;
  esac
}

download_installer() {
  local destination="$1"
  if is_testing && [[ -n "${REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE:-}" ]]; then
    cp -- "${REMOTE_DEV_ANTIGRAVITY_INSTALLER_FIXTURE}" "$destination"
  else
    curl \
      --proto '=https' \
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
  fi
  chmod 0700 "$destination"
  verify_file_identity "Antigravity installer" "$destination" "$expected_installer_size" "$expected_installer_sha"
  /bin/bash -n "$destination" || fail "reviewed Antigravity installer is not valid Bash"
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
    '{
      schema_version: 1,
      installed_at_utc: $installed_at,
      version: $version,
      installer_url: $installer_url,
      installer_sha256: $installer_sha256,
      binary_sha256: $binary_sha256,
      runtime_installed: true,
      bundled_in_image: false
    }' >"$destination"
  chmod 0600 "$destination"
}

install_or_update() {
  local action="$1"
  local assume_yes="$2"
  local had_existing=0 current_version="not installed"

  require_supported_platform
  require_tools
  load_evidence

  if [[ -e "$binary" || -L "$binary" ]]; then
    had_existing=1
    current_version="$(read_verified_version "$binary")"
  fi

  case "$action" in
    install)
      (( had_existing == 0 )) || fail "Antigravity is already installed at $binary; use update"
      ;;
    update)
      (( had_existing == 1 )) || fail "Antigravity is not installed; use install"
      if [[ "$current_version" == "$expected_version" ]]; then
        echo "Antigravity $current_version is already the reviewed version; no download was needed."
        return 0
      fi
      ;;
    *) fail "internal unsupported action: $action" ;;
  esac

  confirm_vendor_download "$action" "$assume_yes"

  local temp_root installer_path isolated_home stage_bin staged_binary staged_manifest final_new
  temp_root="$(mktemp -d "${TMPDIR:-/tmp}/remote-dev-antigravity.XXXXXXXX")"
  trap 'rm -rf -- "$temp_root"' RETURN
  installer_path="$temp_root/install.sh"
  isolated_home="$temp_root/home"
  stage_bin="$temp_root/bin"
  staged_binary="$stage_bin/agy"
  staged_manifest="$temp_root/install.json"
  mkdir -m 0700 -p "$isolated_home" "$stage_bin"

  download_installer "$installer_path"

  if is_testing && [[ -n "${REMOTE_DEV_TEST_AGY_SOURCE:-}" ]]; then
    REMOTE_DEV_TEST_AGY_SOURCE="${REMOTE_DEV_TEST_AGY_SOURCE}" \
      minimal_installer_env "$isolated_home" /bin/bash "$installer_path" --dir "$stage_bin" \
      || fail "reviewed Antigravity installer failed"
  else
    minimal_installer_env "$isolated_home" /bin/bash "$installer_path" --dir "$stage_bin" \
      || fail "reviewed Antigravity installer failed"
  fi

  verify_file_identity "installed Antigravity payload" "$staged_binary" "$expected_binary_size" "$expected_binary_sha"
  chmod 0755 "$staged_binary"
  read_verified_version "$staged_binary" >/dev/null
  write_manifest "$staged_manifest"

  umask 077
  install -d -m 0700 "$bin_dir" "$state_dir" "$vendor_state_dir"
  final_new="$bin_dir/.agy.new.$$"
  install -m 0755 "$staged_binary" "$final_new"
  mv -f -- "$final_new" "$binary"
  install -m 0600 "$staged_manifest" "$manifest.new"
  mv -f -- "$manifest.new" "$manifest"

  echo "Antigravity $expected_version installed from the reviewed Google package."
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

  local version
  version="$(read_verified_version "$binary")"
  if [[ "$menu" == 1 ]]; then
    echo "Antigravity: $version (runtime installed)"
  else
    echo "$version"
  fi
}

main() {
  local command="${1:-}"
  [[ -n "$command" ]] || { usage >&2; exit 2; }
  shift || true

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
