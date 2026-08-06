#!/usr/bin/env bash
set -euo pipefail

readonly OFFICIAL_INSTALLER_URL="https://antigravity.google/cli/install.sh"
readonly MAX_INSTALLER_SIZE=$((2 * 1024 * 1024))
readonly MIN_BINARY_SIZE=$((1024 * 1024))
readonly MAX_BINARY_SIZE=$((1024 * 1024 * 1024))
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
  cat <<'USAGE'
Usage: remote-dev-antigravity <install|update|rollback|status|path> [--yes] [--menu]

Commands:
  install    Install the current official Antigravity CLI from Google.
  update     Explicitly replace the current installation from Google's installer.
  rollback   Restore the previous locally preserved Antigravity installation.
  status     Verify local integrity and report review status.
  path       Print the canonical executable path.

Normal startup never downloads or updates Antigravity. Remote Dev review evidence
is informational and does not gate an intact official-source installation.
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
  rollback_dir="$state_dir/rollback"
  rollback_binary="$rollback_dir/agy"
  rollback_manifest="$rollback_dir/install.json"
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
  require_absolute_safe_path "rollback directory" "$rollback_dir"

  [[ "$evidence" == "$ANTIGRAVITY_EVIDENCE" ]] || fail "production evidence path changed"
  [[ "$bin_dir" == "$ANTIGRAVITY_BIN_DIR" ]] || fail "production binary directory changed"
  [[ "$state_dir" == "$ANTIGRAVITY_STATE_DIR" ]] || fail "production state directory changed"
  [[ "$vendor_state_dir" == "$ANTIGRAVITY_VENDOR_STATE_DIR" ]] || fail "production vendor state directory changed"
  [[ "$binary" == "$ANTIGRAVITY_BINARY" ]] || fail "production binary path changed"
  [[ "$manifest" == "$ANTIGRAVITY_MANIFEST" ]] || fail "production manifest path changed"

  reject_symlink_components "$bin_dir"
  reject_symlink_components "$state_dir"
  reject_symlink_components "$vendor_state_dir"
  reject_symlink_components "$rollback_dir"
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
  for tool in bash curl jq sha256sum stat mktemp install mv date awk sed grep dirname env timeout cp rm mkdir chmod find sort head python3; do
    command -v "$tool" >/dev/null 2>&1 || fail "required command is missing: $tool"
  done
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
    || fail "$label size differs from its local integrity manifest ($actual_size != $trusted_size)"
  actual_sha="$(sha256_file "$path")"
  [[ "$actual_sha" == "$trusted_sha" ]] \
    || fail "$label SHA-256 differs from its local integrity manifest"
}

run_binary_no_update() {
  local candidate="$1"
  shift
  timeout --signal=TERM --kill-after=5s 30s \
    env -i \
      HOME="${HOME:-/root}" \
      USER=root \
      LOGNAME=root \
      SHELL=/bin/bash \
      PATH=/usr/local/bin:/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      TERM=xterm-256color \
      AGY_CLI_DISABLE_AUTO_UPDATE=true \
      CI=1 \
      "$candidate" "$@" \
    </dev/null
}

extract_version() {
  local output="$1"
  local version=""
  version="$(printf '%s\n' "$output" \
    | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+([+-][A-Za-z0-9._-]+)?' \
    | sort -u)"
  [[ -n "$version" && "$version" != *$'\n'* ]] \
    || fail "Antigravity version output did not contain exactly one unambiguous semantic version"
  printf '%s\n' "$version"
}

read_version_with_identity() {
  local candidate="$1"
  local trusted_size="$2"
  local trusted_sha="$3"
  local trusted_version="$4"
  local output version

  verify_file_identity "Antigravity executable" "$candidate" "$trusted_size" "$trusted_sha"
  output="$(run_binary_no_update "$candidate" --version 2>/dev/null)" \
    || fail "Antigravity executable failed its bounded version check"
  version="$(extract_version "$output")"
  [[ "$version" == "$trusted_version" ]] \
    || fail "Antigravity version output differs from its local integrity manifest"
  printf '%s\n' "$version"
}

load_review_evidence() {
  reviewed_version=""
  reviewed_binary_sha=""
  reviewed_binary_size=""
  reviewed_installer_sha=""
  reviewed_installer_size=""
  reviewed_installer_content_type=""

  [[ -r "$evidence" && ! -L "$evidence" ]] || return 0
  if ! jq -e '
      (.schema_version | type == "number") and .schema_version >= 2
      and (.blocking_findings | type == "array") and .blocking_findings == []
      and (.installed_binary.version | type == "string")
      and (.installed_binary.sha256 | type == "string")
      and (.installed_binary.size | type == "number")
    ' "$evidence" >/dev/null 2>&1; then
    return 0
  fi

  reviewed_version="$(jq -r '.installed_binary.version' "$evidence")"
  reviewed_binary_sha="$(jq -r '.installed_binary.sha256' "$evidence")"
  reviewed_binary_size="$(jq -r '.installed_binary.size' "$evidence")"
  reviewed_installer_sha="$(jq -r '.installer.sha256 // empty' "$evidence")"
  reviewed_installer_size="$(jq -r '.installer.size // empty' "$evidence")"
  reviewed_installer_content_type="$(jq -r '.installer.content_type // "application/x-sh"' "$evidence")"
  [[ "$reviewed_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] || reviewed_version=""
  [[ "$reviewed_binary_sha" =~ ^[0-9a-f]{64}$ ]] || reviewed_binary_sha=""
  [[ "$reviewed_binary_size" =~ ^[0-9]+$ ]] || reviewed_binary_size=""
  [[ "$reviewed_installer_sha" =~ ^[0-9a-f]{64}$ ]] || reviewed_installer_sha=""
  [[ "$reviewed_installer_size" =~ ^[0-9]+$ ]] || reviewed_installer_size=""
}

manifest_fields() {
  local manifest_path="$1"
  verify_regular_file "Antigravity install manifest" "$manifest_path"
  jq -e '
      (.schema_version == 1 or .schema_version == 2)
      and (.version | type == "string")
      and (.binary_sha256 | type == "string")
      and (.binary_size | type == "number")
      and (.installer_url == "https://antigravity.google/cli/install.sh")
      and (.runtime_installed == true)
      and (.bundled_in_image == false)
    ' "$manifest_path" >/dev/null \
    || fail "Antigravity install manifest is invalid"

  installed_version="$(jq -r '.version' "$manifest_path")"
  installed_binary_sha="$(jq -r '.binary_sha256' "$manifest_path")"
  installed_binary_size="$(jq -r '.binary_size' "$manifest_path")"
  install_source="$(jq -r '.source // "legacy-schema-1"' "$manifest_path")"
  [[ "$installed_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] \
    || fail "invalid Antigravity version in local manifest"
  [[ "$installed_binary_sha" =~ ^[0-9a-f]{64}$ ]] \
    || fail "invalid Antigravity SHA-256 in local manifest"
  [[ "$installed_binary_size" =~ ^[0-9]+$ ]] \
    || fail "invalid Antigravity size in local manifest"
}

review_status_for() {
  local version="$1"
  local size="$2"
  local sha="$3"
  load_review_evidence
  if [[ -n "$reviewed_version" \
        && "$version" == "$reviewed_version" \
        && "$size" == "$reviewed_binary_size" \
        && "$sha" == "$reviewed_binary_sha" ]]; then
    printf '%s\n' reviewed
  elif [[ -n "$reviewed_version" ]]; then
    printf '%s\n' pending
  else
    printf '%s\n' unavailable
  fi
}

write_manifest() {
  local destination="$1"
  local version="$2"
  local installer_sha="$3"
  local installer_size="$4"
  local installer_content_type="$5"
  local installer_final_url="$6"
  local binary_sha="$7"
  local binary_size="$8"
  local source="$9"
  local installed_at
  installed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

  jq -n \
    --arg installed_at "$installed_at" \
    --arg version "$version" \
    --arg installer_url "$OFFICIAL_INSTALLER_URL" \
    --arg installer_sha256 "$installer_sha" \
    --arg installer_content_type "$installer_content_type" \
    --arg installer_final_url "$installer_final_url" \
    --arg binary_sha256 "$binary_sha" \
    --arg source "$source" \
    --argjson installer_size "$installer_size" \
    --argjson binary_size "$binary_size" \
    '{
      schema_version: 2,
      source: $source,
      installed_at_utc: $installed_at,
      version: $version,
      installer_url: $installer_url,
      installer_final_url: $installer_final_url,
      installer_sha256: $installer_sha256,
      installer_size: $installer_size,
      installer_content_type: $installer_content_type,
      binary_sha256: $binary_sha256,
      binary_size: $binary_size,
      automatic_updates_disabled: true,
      runtime_installed: true,
      bundled_in_image: false
    }' >"$destination"
  chmod 0600 "$destination"
}

repair_manifest_from_review_evidence() {
  load_review_evidence
  [[ -n "$reviewed_version" ]] || return 1
  verify_regular_file "existing Antigravity executable" "$binary"
  local actual_sha actual_size
  actual_sha="$(sha256_file "$binary")"
  actual_size="$(stat -c '%s' "$binary")"
  [[ "$actual_sha" == "$reviewed_binary_sha" && "$actual_size" == "$reviewed_binary_size" ]] \
    || return 1

  install -d -m 0700 "$state_dir"
  local repaired="$state_dir/.install.json.repair.$$"
  local installer_sha installer_size installer_content_type
  installer_sha="$(jq -r '.installer.sha256 // "unknown"' "$evidence")"
  installer_size="$(jq -r '.installer.size // 0' "$evidence")"
  installer_content_type="$(jq -r '.installer.content_type // "unknown"' "$evidence")"
  [[ "$installer_sha" =~ ^[0-9a-f]{64}$ ]] || installer_sha="$(printf '0%.0s' {1..64})"
  [[ "$installer_size" =~ ^[0-9]+$ ]] || installer_size=0
  write_manifest "$repaired" "$reviewed_version" "$installer_sha" "$installer_size" \
    "$installer_content_type" "$OFFICIAL_INSTALLER_URL" "$reviewed_binary_sha" \
    "$reviewed_binary_size" "reviewed-image-evidence"
  mv -f -- "$repaired" "$manifest"
}

read_current_installation() {
  verify_regular_file "existing Antigravity executable" "$binary"
  if [[ ! -r "$manifest" ]]; then
    repair_manifest_from_review_evidence \
      || fail "Antigravity executable has no trusted local manifest; run an explicit update"
  fi
  manifest_fields "$manifest"
  current_version="$(read_version_with_identity \
    "$binary" "$installed_binary_size" "$installed_binary_sha" "$installed_version")" \
    || return $?
  current_review_status="$(review_status_for \
    "$installed_version" "$installed_binary_size" "$installed_binary_sha")" \
    || return $?
}

probe_current_installation() {
  read_current_installation || return $?
  printf '%s\t%s\t%s\n' "$current_version" "$current_review_status" "$install_source"
}

show_vendor_disclosure() {
  cat <<EOF
Antigravity is a Google product and is not distributed by Remote Dev.
The current official installer will be downloaded directly from:
  $OFFICIAL_INSTALLER_URL
A Google account is required for authenticated use.
Google's separate terms and privacy policy apply:
  https://antigravity.google/terms
  https://policies.google.com/privacy
Remote Dev is not affiliated with or endorsed by Google.

The version currently served by Google may be newer than Remote Dev's recorded
review evidence. It will be marked "official, review pending" until that evidence
is refreshed. Installation remains explicit and normal sessions never self-update.
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
  local metadata_path="$2"
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
    --max-filesize "$MAX_INSTALLER_SIZE" \
    --write-out '%{url_effective}\n%{content_type}\n' \
    "$OFFICIAL_INSTALLER_URL" \
    --output "$destination" >"$metadata_path"

  chmod 0700 "$destination"
  verify_regular_file "Antigravity installer" "$destination"
  installer_size="$(stat -c '%s' "$destination")"
  (( installer_size > 0 && installer_size <= MAX_INSTALLER_SIZE )) \
    || fail "official Antigravity installer is empty or exceeds the 2 MiB limit"

  installer_sha="$(sha256_file "$destination")"
  legacy_reviewed_download=0
  mapfile -t download_metadata <"$metadata_path"
  if (( ${#download_metadata[@]} >= 2 )) && [[ -n "${download_metadata[0]}" ]]; then
    installer_final_url="${download_metadata[0]}"
    installer_content_type="${download_metadata[1]%%;*}"
    installer_content_type="${installer_content_type//[[:space:]]/}"
    python3 - "$installer_final_url" <<'PY_ORIGIN' \
      || fail "official installer redirected outside the fixed Google HTTPS origin"
from urllib.parse import urlsplit
import sys
url = urlsplit(sys.argv[1])
valid = (
    url.scheme == "https"
    and url.hostname == "antigravity.google"
    and url.port in {None, 443}
    and url.username is None
    and url.password is None
    and not url.fragment
)
raise SystemExit(0 if valid else 1)
PY_ORIGIN
    case "$installer_content_type" in
      application/x-sh|application/x-shellscript|text/x-shellscript|text/plain|application/octet-stream|"") ;;
      *) fail "official installer returned an unexpected content type: $installer_content_type" ;;
    esac
  elif [[ -n "$reviewed_installer_sha" \
          && "$installer_sha" == "$reviewed_installer_sha" \
          && "$installer_size" == "$reviewed_installer_size" ]]; then
    # Compatibility path for the pre-availability regression harness and for an
    # already reviewed installer. Unknown bytes never enter this path.
    installer_final_url="$OFFICIAL_INSTALLER_URL"
    installer_content_type="${reviewed_installer_content_type:-application/x-sh}"
    legacy_reviewed_download=1
  else
    fail "curl returned incomplete installer origin metadata"
  fi

  if python3 - "$destination" <<'PY_NUL'
from pathlib import Path
import sys
raise SystemExit(0 if b"\x00" in Path(sys.argv[1]).read_bytes() else 1)
PY_NUL
  then
    fail "official installer contains NUL bytes"
  fi
  head -n 1 "$destination" | grep -Eq '^#!.*(ba)?sh([[:space:]]|$)' \
    || fail "official installer has no reviewed shell shebang"
  /bin/bash -n "$destination" || fail "official Antigravity installer is not valid Bash"
}

verify_installer_contract() {
  local installer_path="$1"
  local isolated_home="$2"
  local before after help_output="" help_status=0

  before="$(find "$isolated_home" -mindepth 1 -printf '%P\n' | sort)"
  help_output="$(
    timeout --signal=TERM --kill-after=5s 30s \
      env -i \
        HOME="$isolated_home" \
        USER=root \
        LOGNAME=root \
        SHELL=/bin/bash \
        PATH=/usr/local/bin:/usr/bin:/bin \
        LANG=C.UTF-8 \
        LC_ALL=C.UTF-8 \
        TERM=xterm-256color \
        AGY_CLI_DISABLE_AUTO_UPDATE=true \
        CI=1 \
        /bin/bash "$installer_path" --help \
      </dev/null 2>&1
  )" || help_status=$?
  (( help_status == 0 )) \
    || fail "official Antigravity installer --help failed or exceeded its time limit"
  grep -Eq '(^|[[:space:]])--dir([[:space:]]+|=)<path>([[:space:]]|$)' <<<"$help_output" \
    || fail "official Antigravity installer no longer advertises the required --dir <path> contract"
  after="$(find "$isolated_home" -mindepth 1 -printf '%P\n' | sort)"
  [[ "$before" == "$after" ]] \
    || fail "official installer --help modified the isolated home"
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
      AGY_CLI_DISABLE_AUTO_UPDATE=true \
      CI=1 \
      /bin/bash "$installer_path" --dir "$stage_bin" \
    </dev/null
}

validate_candidate_binary() {
  local candidate="$1"
  local isolated_home="$2"
  verify_regular_file "installed Antigravity payload" "$candidate"
  candidate_size="$(stat -c '%s' "$candidate")"
  [[ -x "$candidate" ]] || fail "installed Antigravity payload is not executable"
  candidate_sha="$(sha256_file "$candidate")"

  if [[ "${legacy_reviewed_download:-0}" == 1 ]]; then
    [[ "$candidate_sha" == "$reviewed_binary_sha" \
       && "$candidate_size" == "$reviewed_binary_size" ]] \
      || fail "installed payload differs from the reviewed legacy fixture before execution"
  else
    (( candidate_size >= MIN_BINARY_SIZE && candidate_size <= MAX_BINARY_SIZE )) \
      || fail "installed Antigravity payload size is outside the reviewed safety bounds"
    python3 - "$candidate" <<'PY_ELF' \
      || fail "installed Antigravity payload is not a Linux AMD64 ELF executable"
from pathlib import Path
import struct
import sys
header = Path(sys.argv[1]).read_bytes()[:64]
if len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2:
    raise SystemExit(1)
if header[5] == 1:
    endian = "<"
elif header[5] == 2:
    endian = ">"
else:
    raise SystemExit(1)
e_type, e_machine = struct.unpack_from(endian + "HH", header, 16)
raise SystemExit(0 if e_type in {2, 3} and e_machine == 62 else 1)
PY_ELF
  fi
  local version_output help_status=0
  version_output="$(
    HOME="$isolated_home" run_binary_no_update "$candidate" --version 2>/dev/null
  )" || fail "installed Antigravity payload failed its bounded version check"
  candidate_version="$(extract_version "$version_output")"
  HOME="$isolated_home" run_binary_no_update "$candidate" --help >/dev/null 2>&1 \
    || help_status=$?
  (( help_status == 0 )) || fail "installed Antigravity payload failed its bounded help check"
}

save_rollback_copy() {
  local source_binary="$1"
  local source_manifest="$2"
  verify_regular_file "current Antigravity executable" "$source_binary"
  verify_regular_file "current Antigravity manifest" "$source_manifest"
  install -d -m 0700 "$rollback_dir"
  local next_binary="$rollback_dir/.agy.new.$$"
  local next_manifest="$rollback_dir/.install.json.new.$$"
  install -m 0700 "$source_binary" "$next_binary"
  install -m 0600 "$source_manifest" "$next_manifest"
  mv -f -- "$next_binary" "$rollback_binary"
  mv -f -- "$next_manifest" "$rollback_manifest"
}

publish_candidate() {
  local staged_binary="$1"
  local staged_manifest="$2"
  local preserve_current="$3"
  local final_new="$bin_dir/.agy.new.$$"
  local manifest_new="$state_dir/.install.json.new.$$"
  local emergency_binary="$cleanup_root/current-agy"
  local emergency_manifest="$cleanup_root/current-install.json"
  local had_binary=0 had_manifest=0

  if [[ -f "$binary" && ! -L "$binary" ]]; then
    install -m 0700 "$binary" "$emergency_binary"
    had_binary=1
  fi
  if [[ -f "$manifest" && ! -L "$manifest" ]]; then
    install -m 0600 "$manifest" "$emergency_manifest"
    had_manifest=1
  fi
  if [[ "$preserve_current" == 1 && "$had_binary" == 1 && "$had_manifest" == 1 ]]; then
    save_rollback_copy "$binary" "$manifest"
  fi

  install -m 0700 "$staged_binary" "$final_new"
  install -m 0600 "$staged_manifest" "$manifest_new"
  mv -f -- "$final_new" "$binary"
  if ! mv -f -- "$manifest_new" "$manifest"; then
    if (( had_binary )); then install -m 0700 "$emergency_binary" "$binary"; else rm -f -- "$binary"; fi
    if (( had_manifest )); then install -m 0600 "$emergency_manifest" "$manifest"; else rm -f -- "$manifest"; fi
    fail "publishing the Antigravity manifest failed; the previous installation was restored"
  fi
}

install_or_update() {
  local action="$1"
  local assume_yes="$2"
  local current_version="not installed"
  local current_valid=0

  require_supported_platform
  require_tools
  load_review_evidence

  local binary_present=0
  if [[ -e "$binary" || -L "$binary" ]]; then binary_present=1; fi
  case "$action" in
    install)
      (( binary_present == 0 )) || fail "Antigravity is already installed at $binary; use update"
      ;;
    update)
      (( binary_present == 1 )) || fail "Antigravity is not installed; use install"
      local current_probe=""
      if current_probe="$(probe_current_installation 2>/dev/null)"; then
        IFS=$'\t' read -r current_version current_review_status current_install_source <<<"$current_probe"
        current_valid=1
      else
        current_version="damaged or locally modified installation"
      fi
      ;;
    *) fail "internal unsupported action: $action" ;;
  esac

  confirm_vendor_download "$action" "$assume_yes"

  install -d -m 0700 "$state_dir"
  reject_symlink_components "$state_dir"
  cleanup_root="$(mktemp -d "$state_dir/remote-dev-antigravity.XXXXXXXX")"
  local installer_path="$cleanup_root/install.sh"
  local installer_metadata="$cleanup_root/download-metadata"
  local isolated_home="$cleanup_root/home"
  local stage_bin="$cleanup_root/bin"
  local staged_binary="$stage_bin/agy"
  local staged_manifest="$cleanup_root/install.json"
  mkdir -m 0700 -p "$isolated_home" "$stage_bin"

  download_installer "$installer_path" "$installer_metadata"
  verify_installer_contract "$installer_path" "$isolated_home"
  run_installer_isolated "$installer_path" "$isolated_home" "$stage_bin" \
    || fail "official Antigravity installer failed or exceeded its time limit"
  validate_candidate_binary "$staged_binary" "$isolated_home"
  local manifest_source="official-google-installer"
  if [[ "${legacy_reviewed_download:-0}" == 1 ]]; then
    manifest_source="reviewed-image-evidence"
  fi
  write_manifest "$staged_manifest" "$candidate_version" "$installer_sha" \
    "$installer_size" "$installer_content_type" "$installer_final_url" "$candidate_sha" \
    "$candidate_size" "$manifest_source"

  umask 077
  install -d -m 0700 "$bin_dir" "$state_dir" "$vendor_state_dir"
  publish_candidate "$staged_binary" "$staged_manifest" "$current_valid"

  local review_status
  review_status="$(review_status_for "$candidate_version" "$candidate_size" "$candidate_sha")"
  if [[ "$action" == update ]]; then
    echo "Antigravity updated from Google: $current_version -> $candidate_version"
  else
    echo "Antigravity $candidate_version installed from Google's official installer."
  fi
  case "$review_status" in
    reviewed) echo "Review status: official and reviewed by Remote Dev." ;;
    pending) echo "Review status: official installation; Remote Dev review pending." ;;
    unavailable) echo "Review status: official installation; Remote Dev review evidence unavailable." ;;
  esac
  echo "Executable: $binary"
  echo "Automatic CLI updates remain disabled during Remote Dev launches."
}

rollback_command() {
  require_tools
  verify_regular_file "rollback Antigravity executable" "$rollback_binary"
  verify_regular_file "rollback Antigravity manifest" "$rollback_manifest"

  manifest_fields "$rollback_manifest"
  local previous_version previous_size previous_sha
  previous_version="$installed_version"
  previous_size="$installed_binary_size"
  previous_sha="$installed_binary_sha"
  read_version_with_identity "$rollback_binary" "$previous_size" "$previous_sha" "$previous_version" >/dev/null

  local current_valid=0 current_version="damaged or unavailable" current_probe=""
  if [[ -f "$binary" && ! -L "$binary" && -r "$manifest" ]]; then
    if current_probe="$(probe_current_installation 2>/dev/null)"; then
      IFS=$'\t' read -r current_version current_review_status current_install_source <<<"$current_probe"
      current_valid=1
    fi
  fi

  cleanup_root="$(mktemp -d "$state_dir/remote-dev-antigravity-rollback.XXXXXXXX")"
  local staged_binary="$cleanup_root/agy"
  local staged_manifest="$cleanup_root/install.json"
  install -m 0700 "$rollback_binary" "$staged_binary"
  install -m 0600 "$rollback_manifest" "$staged_manifest"
  publish_candidate "$staged_binary" "$staged_manifest" "$current_valid"
  echo "Antigravity restored: $current_version -> $previous_version"
}

status_command() {
  local menu="$1"
  require_tools
  load_review_evidence
  if [[ ! -e "$binary" && ! -L "$binary" ]]; then
    if [[ "$menu" == 1 ]]; then echo "Antigravity: not installed"; else echo "not installed"; fi
    return 0
  fi

  local current_version="" current_review_status="" current_install_source="" current_probe=""
  if ! current_probe="$(probe_current_installation 2>/dev/null)"; then
    if [[ "$menu" == 1 ]]; then
      echo "Antigravity: damaged, locally modified, or unverified installation (explicit update required)"
    else
      echo "damaged, locally modified, or unverified installation requires explicit update"
    fi
    return 3
  fi
  IFS=$'\t' read -r current_version current_review_status current_install_source <<<"$current_probe"

  if [[ "$menu" == 1 ]]; then
    case "$current_review_status" in
      reviewed)
        if [[ "$current_install_source" == reviewed-image-evidence ]]; then
          echo "Antigravity: $current_version (runtime installed)"
        else
          echo "Antigravity: $current_version (official, reviewed)"
        fi
        ;;
      pending) echo "Antigravity: $current_version (official, review pending)" ;;
      unavailable) echo "Antigravity: $current_version (official, review unavailable)" ;;
    esac
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
    rollback) rollback_command ;;
    status) status_command "$menu" ;;
    path) printf '%s\n' "$binary" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
