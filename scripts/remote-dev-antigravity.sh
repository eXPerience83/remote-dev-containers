#!/usr/bin/env bash
set -euo pipefail

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
unset antigravity_lib antigravity_lib_path

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
