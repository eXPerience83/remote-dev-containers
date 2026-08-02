#!/usr/bin/env bash
set -euo pipefail

skip_aliases=0
skip_path=0
for argument in "$@"; do
  case "$argument" in
    --skip-aliases) skip_aliases=1 ;;
    --skip-path) skip_path=1 ;;
    *) printf 'unexpected argument: %s\n' "$argument" >&2; exit 2 ;;
  esac
done

if [[ "$skip_aliases" != 1 || "$skip_path" != 1 ]]; then
  printf 'required safety flags were not supplied\n' >&2
  exit 3
fi

install_dir="${HOME}/.local/bin"
mkdir -p "$install_dir"
cat >"${install_dir}/agy" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version)
    printf 'Antigravity CLI 0.0.0-fixture\n'
    ;;
  --help)
    printf 'Usage: agy [options]\n'
    ;;
  *)
    printf 'fixture does not authenticate\n' >&2
    exit 4
    ;;
esac
EOF
chmod 0755 "${install_dir}/agy"
printf 'fixture installation complete\n'
