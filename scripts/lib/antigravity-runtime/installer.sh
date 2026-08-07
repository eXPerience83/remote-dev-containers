show_vendor_disclosure() {
  cat <<EOF_DISCLOSURE
Antigravity is a Google product and is not distributed by Remote Dev.
The current installer will be downloaded directly from:
  $OFFICIAL_INSTALLER_URL
A Google account is required for authenticated use.
Google's separate terms and privacy policy apply:
  https://antigravity.google/terms
  https://policies.google.com/privacy
Remote Dev is not affiliated with or endorsed by Google.

A compatible official-source version may be installed before Remote Dev has
committed review evidence for that exact payload. Its local integrity will be
verified against a private manifest and its status will be shown as review pending.
EOF_DISCLOSURE
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
  local metadata="$2"
  local current_url="$OFFICIAL_INSTALLER_URL"
  local hop=0

  while (( hop <= MAX_INSTALLER_REDIRECTS )); do
    local hop_body="$cleanup_root/install-hop-${hop}.body"
    local hop_metadata="$cleanup_root/install-hop-${hop}.metadata"
    if ! curl \
      --disable \
      --proto '=https' \
      --proto-redir '=https' \
      --tlsv1.2 \
      --fail \
      --silent \
      --show-error \
      --retry 3 \
      --retry-all-errors \
      --connect-timeout 10 \
      --max-time 300 \
      --max-filesize "$MAX_INSTALLER_SIZE" \
      --max-redirs 0 \
      --write-out '%{http_code}\n%{url_effective}\n%{content_type}\n%header{location}\n' \
      "$current_url" \
      --output "$hop_body" >"$hop_metadata"; then
      fail "official Antigravity installer download failed"
    fi

    mapfile -t download_metadata <"$hop_metadata"
    [[ "${#download_metadata[@]}" -eq 4 ]] \
      || fail "official installer download returned malformed metadata"
    local response_code="${download_metadata[0]}"
    local effective_url="${download_metadata[1]}"
    local content_type="${download_metadata[2]}"
    local location="${download_metadata[3]}"

    [[ "$response_code" =~ ^[0-9]{3}$ ]] \
      || fail "official installer returned an invalid HTTP status"
    safe_official_url "$effective_url" \
      || fail "official installer request left the reviewed Google origin"

    case "$response_code" in
      200)
        chmod 0700 "$hop_body"
        verify_file_bounds "Antigravity installer" "$hop_body" "$MAX_INSTALLER_SIZE"
        mv -f -- "$hop_body" "$destination"
        printf '%s\n%s\n' "$effective_url" "$content_type" >"$metadata"
        candidate_installer_final_url="$effective_url"
        candidate_installer_size="$(stat -c '%s' "$destination")"
        candidate_installer_sha="$(sha256_file "$destination")"
        break
        ;;
      301|302|303|307|308)
        (( hop < MAX_INSTALLER_REDIRECTS )) \
          || fail "official installer exceeded the supported redirect limit"
        [[ -n "$location" ]] || fail "official installer redirect omitted its Location header"
        local next_url=""
        next_url="$(resolve_official_redirect "$current_url" "$location")" \
          || fail "official installer redirect left the reviewed Google origin"
        safe_official_url "$next_url" \
          || fail "official installer redirect left the reviewed Google origin"
        rm -f -- "$hop_body"
        current_url="$next_url"
        hop=$((hop + 1))
        continue
        ;;
      *)
        fail "official installer returned unsupported HTTP status $response_code"
        ;;
    esac
  done

  verify_owned_regular_file "Antigravity installer" "$destination"
  /bin/bash -n "$destination" || fail "official Antigravity installer is not valid Bash"
  grep -Eq -- '(^|[^A-Za-z0-9_-])--dir([^A-Za-z0-9_-]|$)' "$destination" \
    || fail "official Antigravity installer no longer contains the required --dir contract"
}

verify_installer_contract() {
  local installer_path="$1"
  local isolated_home="$2"
  local stdout_path="$3"
  local stderr_path="$4"
  run_unprivileged_bounded \
    "$stdout_path" "$stderr_path" 30 "$isolated_home" "$CAPTURE_LIMIT_BLOCKS" \
    env -i \
      HOME="$isolated_home" \
      USER="$sandbox_user" \
      LOGNAME="$sandbox_user" \
      SHELL=/bin/bash \
      PATH=/usr/local/bin:/usr/bin:/bin \
      LANG=C.UTF-8 \
      LC_ALL=C.UTF-8 \
      TERM=xterm-256color \
      AGY_CLI_DISABLE_AUTO_UPDATE=true \
      CI=1 \
      /bin/bash "$installer_path" --help \
    || fail "official Antigravity installer --help failed or exceeded its limit"
  grep -Eq '(^|[[:space:]])--dir[[:space:]]+<path>([[:space:]]|$)' \
    "$stdout_path" "$stderr_path" \
    || fail "official Antigravity installer no longer advertises the required --dir <path> contract"
  profile_paths_unchanged "$isolated_home"
}

run_installer_isolated() {
  local installer_path="$1"
  local isolated_home="$2"
  local stage_bin="$3"
  local stdout_path="$4"
  local stderr_path="$5"
  run_unprivileged_bounded \
    "$stdout_path" "$stderr_path" 900 "$isolated_home" "$INSTALLER_RUN_FILE_LIMIT_BLOCKS" \
    env -i \
      HOME="$isolated_home" \
      USER="$sandbox_user" \
      LOGNAME="$sandbox_user" \
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
      /bin/bash "$installer_path" --dir "$stage_bin"
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

  publish_old_binary_backup="$cleanup_root/previous-agy"
  publish_old_manifest_backup="$cleanup_root/previous-install.json"
  publish_had_old_binary=0
  publish_had_old_manifest=0

  if [[ -f "$binary" && ! -L "$binary" ]]; then
    install -m 0700 "$binary" "$publish_old_binary_backup"
    publish_had_old_binary=1
  fi
  if [[ -f "$manifest" && ! -L "$manifest" ]]; then
    install -m 0600 "$manifest" "$publish_old_manifest_backup"
    publish_had_old_manifest=1
  fi

  install -m 0700 "$staged_binary" "$final_new"
  install -m 0600 "$staged_manifest" "$manifest_new"
  publish_in_progress=1
  mv -f -- "$final_new" "$binary"
  mv -f -- "$manifest_new" "$manifest"
  verify_file_identity "published Antigravity executable" "$binary" "$candidate_binary_size" "$candidate_binary_sha"
  verify_file_identity "published Antigravity manifest" "$manifest" "$(stat -c '%s' "$staged_manifest")" "$(sha256_file "$staged_manifest")"
  publish_in_progress=0
}
