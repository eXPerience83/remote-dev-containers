#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--help" ]]; then
  cat <<'EOF'
Usage: install.sh [options]
Options:
  -d, --dir <path>    Specify a custom directory to install the binary
  -h, --help          Display this help menu
EOF
  exit 0
fi

install_dir=""
while (($#)); do
  case "$1" in
    -d|--dir)
      [[ $# -ge 2 ]] || { printf 'missing directory argument\n' >&2; exit 2; }
      install_dir="$2"
      shift 2
      ;;
    *)
      printf 'unexpected argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

[[ -n "$install_dir" ]] || { printf 'custom install directory required\n' >&2; exit 3; }
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
