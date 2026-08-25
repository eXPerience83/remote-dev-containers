load_local_manifest() {
  manifest_schema=""
  manifest_version=""
  manifest_installer_url=""
  manifest_installer_final_url=""
  manifest_installer_sha=""
  manifest_installer_size=""
  manifest_binary_sha=""
  manifest_binary_size=""

  owned_regular_file_matches "$manifest" || return 1
  local mode
  mode="$(stat -c '%a' "$manifest" 2>/dev/null)" || return 1
  (( (8#$mode & 077) == 0 )) || return 1

  manifest_schema="$(jq -er '.schema_version' "$manifest" 2>/dev/null)" || return 1
  case "$manifest_schema" in
    1)
      jq -e '
        .schema_version == 1
        and .runtime_installed == true
        and .bundled_in_image == false
        and (.version | type == "string")
        and (.installer_url | type == "string")
        and (.installer_sha256 | type == "string")
        and (.binary_sha256 | type == "string")
        and (.binary_size | type == "number")
      ' "$manifest" >/dev/null 2>&1 || return 1
      manifest_version="$(jq -er '.version' "$manifest")" || return 1
      manifest_installer_url="$(jq -er '.installer_url' "$manifest")" || return 1
      manifest_installer_final_url="$manifest_installer_url"
      manifest_installer_sha="$(jq -er '.installer_sha256' "$manifest")" || return 1
      manifest_binary_sha="$(jq -er '.binary_sha256' "$manifest")" || return 1
      manifest_binary_size="$(jq -er '.binary_size' "$manifest")" || return 1
      ;;
    2)
      jq -e '
        .schema_version == 2
        and .source == "official-google-installer"
        and .runtime_installed == true
        and .bundled_in_image == false
        and .automatic_updates_disabled == true
        and (.version | type == "string")
        and (.installer_url | type == "string")
        and (.installer_final_url | type == "string")
        and (.installer_sha256 | type == "string")
        and (.installer_size | type == "number")
        and (.binary_sha256 | type == "string")
        and (.binary_size | type == "number")
      ' "$manifest" >/dev/null 2>&1 || return 1
      manifest_version="$(jq -er '.version' "$manifest")" || return 1
      manifest_installer_url="$(jq -er '.installer_url' "$manifest")" || return 1
      manifest_installer_final_url="$(jq -er '.installer_final_url' "$manifest")" || return 1
      manifest_installer_sha="$(jq -er '.installer_sha256' "$manifest")" || return 1
      manifest_installer_size="$(jq -er '.installer_size' "$manifest")" || return 1
      manifest_binary_sha="$(jq -er '.binary_sha256' "$manifest")" || return 1
      manifest_binary_size="$(jq -er '.binary_size' "$manifest")" || return 1
      ;;
    *) return 1 ;;
  esac

  [[ "$manifest_version" =~ ^[0-9]+([.][0-9]+){1,3}([+-][A-Za-z0-9._-]+)?$ ]] || return 1
  [[ "$manifest_installer_url" == "$OFFICIAL_INSTALLER_URL" ]] || return 1
  safe_official_url "$manifest_installer_final_url" || return 1
  [[ "$manifest_installer_sha" =~ ^[0-9a-f]{64}$ ]] || return 1
  [[ "$manifest_binary_sha" =~ ^[0-9a-f]{64}$ ]] || return 1
  [[ "$manifest_binary_size" =~ ^[0-9]+$ && "$manifest_binary_size" -gt 0 && "$manifest_binary_size" -le "$MAX_BINARY_SIZE" ]] || return 1
  if [[ "$manifest_schema" == 2 ]]; then
    [[ "$manifest_installer_size" =~ ^[0-9]+$ && "$manifest_installer_size" -gt 0 && "$manifest_installer_size" -le "$MAX_INSTALLER_SIZE" ]] || return 1
  fi
}

review_values_match() {
  local schema="$1"
  local version="$2"
  local binary_sha="$3"
  local binary_size="$4"
  local installer_sha="$5"
  local installer_size="$6"

  [[ "$version" == "$reviewed_version"
     && "$binary_sha" == "$reviewed_binary_sha"
     && "$binary_size" == "$reviewed_binary_size"
     && "$installer_sha" == "$reviewed_installer_sha" ]] || return 1
  if [[ "$schema" == 2 ]]; then
    [[ "$installer_size" == "$reviewed_installer_size" ]] || return 1
  fi
}

manifest_is_reviewed() {
  review_values_match \
    "$manifest_schema" \
    "$manifest_version" \
    "$manifest_binary_sha" \
    "$manifest_binary_size" \
    "$manifest_installer_sha" \
    "$manifest_installer_size"
}

write_manifest() {
  local destination="$1"
  local installed_at
  installed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  install -m 0600 /dev/null "$destination"
  jq -n \
    --arg installed_at "$installed_at" \
    --arg version "$candidate_version" \
    --arg installer_url "$OFFICIAL_INSTALLER_URL" \
    --arg installer_final_url "$candidate_installer_final_url" \
    --arg installer_sha256 "$candidate_installer_sha" \
    --argjson installer_size "$candidate_installer_size" \
    --arg binary_sha256 "$candidate_binary_sha" \
    --argjson binary_size "$candidate_binary_size" \
    '{
      schema_version: 2,
      source: "official-google-installer",
      installed_at_utc: $installed_at,
      version: $version,
      installer_url: $installer_url,
      installer_final_url: $installer_final_url,
      installer_sha256: $installer_sha256,
      installer_size: $installer_size,
      binary_sha256: $binary_sha256,
      binary_size: $binary_size,
      runtime_installed: true,
      bundled_in_image: false,
      automatic_updates_disabled: true
    }' >"$destination"
}

inspect_local_installation() {
  current_state="damaged"
  current_version="damaged or locally modified"

  if [[ ! -e "$binary" && ! -L "$binary" && ! -e "$manifest" && ! -L "$manifest" ]]; then
    current_state="absent"
    current_version="not installed"
    return 0
  fi

  # Passive status and launch checks never repair persistent state. Either half
  # of the executable/manifest pair being absent requires an explicit update.
  if [[ ! -e "$binary" && ! -L "$binary" ]] || [[ ! -e "$manifest" && ! -L "$manifest" ]]; then
    return 1
  fi

  load_local_manifest || return 1
  file_metadata_matches "$binary" "$manifest_binary_size" || return 1

  current_version="$manifest_version"
  if manifest_is_reviewed; then
    current_state="reviewed"
  else
    current_state="review-pending"
  fi
}

verify_local_installation() {
  inspect_local_installation || return $?
  [[ "$current_state" == absent ]] && return 0
  if ! file_identity_matches "$binary" "$manifest_binary_size" "$manifest_binary_sha"; then
    current_state="damaged"
    current_version="damaged or locally modified"
    return 1
  fi
}
