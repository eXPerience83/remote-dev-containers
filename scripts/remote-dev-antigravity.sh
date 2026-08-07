#!/bin/bash -p
set -euo pipefail

# The supported container executes this manager as root against canonical /root
# state. Ignore caller shell startup hooks/functions and pin root command lookup
# to image-owned system paths before loading the immutable runtime libraries.
builtin unset BASH_ENV ENV
if (( EUID == 0 )); then
  PATH=/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin
  builtin export PATH
  builtin hash -r
fi

# These commands are the complete external-tool contract used by the runtime
# libraries. Remove inherited shell functions with matching names so normal
# command dispatch cannot shadow the checked executable after startup.
# shellcheck disable=SC2034
readonly -a ANTIGRAVITY_RUNTIME_TOOLS=(
  bash curl jq sha256sum stat mktemp install mv date awk sed grep dirname env
  timeout rm chmod chown id readelf setpriv python3 cat uname
)
for runtime_tool in "${ANTIGRAVITY_RUNTIME_TOOLS[@]}"; do
  builtin unset -f "$runtime_tool" 2>/dev/null || true
done
builtin unset runtime_tool

# These declarations form the state contract consumed by the immutable
# antigravity-runtime libraries sourced below.
# shellcheck disable=SC2034
readonly \
  OFFICIAL_INSTALLER_URL="https://antigravity.google/cli/install.sh" \
  MAX_INSTALLER_SIZE=$((2 * 1024 * 1024)) \
  MAX_BINARY_SIZE=$((512 * 1024 * 1024)) \
  MAX_INSTALLER_REDIRECTS=5 \
  CAPTURE_LIMIT_BLOCKS=2048

# Immutable library paths consumed before command dispatch.
# shellcheck disable=SC2034
readonly paths_lib=/usr/local/lib/remote-dev/antigravity-paths.sh
# shellcheck disable=SC2034
readonly runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh
# shellcheck disable=SC2034
readonly antigravity_lib_dir=/usr/local/lib/remote-dev/antigravity-runtime

# This dependent limit must be evaluated after MAX_BINARY_SIZE is assigned.
# shellcheck disable=SC2034
readonly INSTALLER_RUN_FILE_LIMIT_BLOCKS=$(((MAX_BINARY_SIZE + 1023) / 1024))

# shellcheck disable=SC2034
declare -g \
  cleanup_root="" \
  verification_root="" \
  publish_in_progress=0 \
  publish_had_old_binary=0 \
  publish_had_old_manifest=0 \
  publish_old_binary_backup="" \
  publish_old_manifest_backup="" \
  sandbox_uid="" \
  sandbox_gid="" \
  sandbox_user="" \
  sandbox_requires_drop=0

for antigravity_lib in core integrity manifest installer commands; do
  antigravity_lib_path="$antigravity_lib_dir/$antigravity_lib.sh"
  [[ -f "$antigravity_lib_path" && -r "$antigravity_lib_path" && ! -L "$antigravity_lib_path" ]] \
    || { printf 'ERROR: immutable Antigravity runtime library is unavailable: %s\n' "$antigravity_lib_path" >&2; exit 1; }
  # shellcheck source=/dev/null
  source "$antigravity_lib_path"
done
builtin unset antigravity_lib antigravity_lib_path

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
      *) fail "unknown argument: $1" ;;
    esac
    shift
  done

  resolve_paths
  validate_paths

  case "$command" in
    install|update) install_or_update "$command" "$assume_yes" ;;
    status) status_command "$menu" ;;
    path) printf '%s\n' "$binary" ;;
    -h|--help|help) usage ;;
    *) usage >&2; exit 2 ;;
  esac
}

main "$@"
