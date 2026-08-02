#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
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

if [[ -x "${install_dir}/agy" ]]; then
  printf 'already installed; self-updates in the background\n'
  exit 0
fi

source_file="${install_dir}/agy-fixture.c"
cat >"$source_file" <<'EOF'
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("Antigravity CLI 0.0.0-fixture");
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "--help") == 0) {
        fputs("Usage of agy:\n  update\n  install\n  --sandbox\n  --dangerously-skip-permissions\n", stderr);
        return 0;
    }
    return 4;
}
EOF
cc -O2 -s -o "${install_dir}/agy" "$source_file"
rm -f "$source_file"
printf 'linux_amd64 download complete and checksum verified\n'
printf 'UNTRUSTED_VENDOR_OUTPUT_SHOULD_NOT_APPEAR\n' >&2
