candidate_review_state() {
  if review_values_match \
    2 \
    "$candidate_version" \
    "$candidate_binary_sha" \
    "$candidate_binary_size" \
    "$candidate_installer_sha" \
    "$candidate_installer_size"; then
    printf '%s\n' reviewed
  else
    printf '%s\n' review-pending
  fi
}

install_or_update() {
  local action="$1"
  local assume_yes="$2"
  local previous_version="not installed"

  require_tools
  require_supported_platform
  load_evidence
  resolve_sandbox_identity

  local binary_present=0 manifest_present=0 installation_present=0
  if [[ -e "$binary" || -L "$binary" ]]; then
    binary_present=1
  fi
  if [[ -e "$manifest" || -L "$manifest" ]]; then
    manifest_present=1
  fi
  if (( binary_present || manifest_present )); then
    installation_present=1
  fi

  case "$action" in
    install)
      (( installation_present == 0 )) \
        || fail "Antigravity installation state already exists; use update to repair or replace it"
      ;;
    update)
      (( installation_present == 1 )) || fail "Antigravity is not installed; use install"
      if (( manifest_present )) && [[ ! -L "$manifest" ]] && load_local_manifest; then
        previous_version="$manifest_version"
      else
        previous_version="damaged or locally modified installation"
      fi
      ;;
    *) fail "internal unsupported action: $action" ;;
  esac

  confirm_vendor_download "$action" "$assume_yes"

  install -d -m 0700 "$state_dir"
  reject_symlink_components "$state_dir"
  cleanup_root="$(mktemp -d "$state_dir/remote-dev-antigravity.XXXXXXXX")"
  local sandbox_root="$cleanup_root/sandbox"
  local installer_path="$sandbox_root/install.sh"
  local isolated_home="$sandbox_root/home"
  local stage_bin="$sandbox_root/bin"
  local staged_binary="$stage_bin/agy"
  local staged_manifest="$cleanup_root/install.json"
  local inspection_dir="$cleanup_root/inspection"

  # Only the isolated home, destination and installer are writable by the
  # vendor process. Capture paths stay root-owned so root redirections cannot
  # follow a symlink planted by changed installer or candidate code.
  install -d -m 0700 "$sandbox_root" "$inspection_dir"
  install -d -m 0700 "$isolated_home" "$stage_bin"
  chown -R "$sandbox_uid:$sandbox_gid" "$sandbox_root"

  download_installer "$installer_path"
  chown "$sandbox_uid:$sandbox_gid" "$installer_path"

  # Keep the root-owned staging ancestors private. The isolated user receives
  # only one inherited descriptor for its own sandbox subtree.
  local sandbox_fd
  exec {sandbox_fd}<"$sandbox_root"
  local sandbox_exec="/proc/self/fd/$sandbox_fd"
  local installer_exec="$sandbox_exec/install.sh"
  local isolated_home_exec="$sandbox_exec/home"
  local stage_bin_exec="$sandbox_exec/bin"
  local staged_binary_exec="$stage_bin_exec/agy"

  verify_installer_contract \
    "$installer_exec" "$isolated_home_exec" \
    "$inspection_dir/installer-help.out" "$inspection_dir/installer-help.err"
  run_installer_isolated \
    "$installer_exec" "$isolated_home_exec" "$stage_bin_exec" \
    "$inspection_dir/installer-run.out" "$inspection_dir/installer-run.err" \
    || fail "official Antigravity installer failed or exceeded its time limit"
  inspect_binary_candidate \
    "$staged_binary" "$staged_binary_exec" "$isolated_home_exec" "$inspection_dir"
  exec {sandbox_fd}<&-
  write_manifest "$staged_manifest"

  umask 077
  install -d -m 0700 "$bin_dir" "$state_dir" "$vendor_state_dir"
  publish_verified_install "$staged_binary" "$staged_manifest"

  local review_state
  review_state="$(candidate_review_state)"
  if [[ "$action" == update ]]; then
    echo "Antigravity updated explicitly: $previous_version -> $candidate_version"
  else
    echo "Antigravity $candidate_version installed from Google's official installer."
  fi
  if [[ "$review_state" == reviewed ]]; then
    echo "Review state: official and reviewed by Remote Dev evidence."
  else
    echo "Review state: official source; Remote Dev review pending."
  fi
  echo "Executable: $binary"
  echo "Automatic CLI updates remain disabled during Remote Dev launches."
}

status_command() {
  local menu="$1"
  require_tools
  load_evidence

  verification_root="$(mktemp -d)"
  local status=0
  verify_local_installation "$verification_root" || status=$?
  rm -rf -- "$verification_root"
  verification_root=""

  if (( status != 0 )) || [[ "$current_state" == damaged ]]; then
    if [[ "$menu" == 1 ]]; then
      echo "Antigravity: damaged or locally modified (explicit update required)"
    else
      echo "damaged or locally modified; explicit update required" >&2
    fi
    return 3
  fi

  case "$current_state" in
    absent)
      if [[ "$menu" == 1 ]]; then
        echo "Antigravity: not installed"
      else
        echo "not installed"
      fi
      ;;
    reviewed)
      if [[ "$menu" == 1 ]]; then
        echo "Antigravity: $current_version (official and reviewed)"
      else
        echo "$current_version"
      fi
      ;;
    review-pending)
      if [[ "$menu" == 1 ]]; then
        echo "Antigravity: $current_version (official source; Remote Dev review pending)"
      else
        echo "$current_version"
      fi
      ;;
    *) fail "internal unsupported Antigravity state: $current_state" ;;
  esac
}
