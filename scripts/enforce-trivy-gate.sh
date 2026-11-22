#!/usr/bin/env bash
# Shared build/Edge/stable fixable-CRITICAL gate: image coverage is mandatory.
# Publication calls MUST also bind each report to the expected immutable manifest.
set -euo pipefail

if (( $# == 0 )); then
  echo "Usage: $0 [--expect-image=immutable-ref] [--expect-ubuntu=VERSION] label:report.json [...]" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
failed=0
count=0
expected_image=""
expected_ubuntu=""

for entry in "$@"; do
  case "$entry" in
    --expect-image=*)
      [[ -z "$expected_image" ]] || { echo "ERROR: duplicate expected image" >&2; exit 2; }
      expected_image="${entry#--expect-image=}"
      [[ -n "$expected_image" ]] || { echo "ERROR: missing expected image" >&2; exit 2; }
      continue
      ;;
    --expect-ubuntu=*)
      [[ -z "$expected_ubuntu" ]] || { echo "ERROR: duplicate Ubuntu release" >&2; exit 2; }
      expected_ubuntu="${entry#--expect-ubuntu=}"
      [[ -n "$expected_ubuntu" ]] || { echo "ERROR: missing Ubuntu release" >&2; exit 2; }
      continue
      ;;
    -*)
      echo "ERROR: unsupported Trivy gate option: $entry" >&2
      exit 2
      ;;
  esac

  if [[ "$entry" != *:* ]]; then
    echo "ERROR: invalid Trivy gate argument (expected label:report): $entry" >&2
    exit 2
  fi
  label="${entry%%:*}"
  report="${entry#*:}"
  [[ -n "$label" && -n "$report" ]] || { echo "ERROR: empty Trivy label/report" >&2; exit 2; }
  args=("$report")
  if [[ -n "$expected_image" ]]; then args+=("--expect-image=$expected_image"); fi
  if [[ -n "$expected_ubuntu" ]]; then args+=("--expect-ubuntu=$expected_ubuntu"); fi

  echo "Checking Trivy coverage and critical vulnerabilities: $label"
  if ! python3 "$root/scripts/validate-trivy-image-report.py" "${args[@]}"; then
    echo "ERROR: Trivy gate rejected $label" >&2
    failed=1
  fi
  expected_image=""
  expected_ubuntu=""
  count=$((count + 1))
done

if (( count == 0 )) || [[ -n "$expected_image" || -n "$expected_ubuntu" ]]; then
  echo "ERROR: unmatched expected image/OS option or no reports" >&2
  exit 2
fi
if (( failed != 0 )); then
  echo "ERROR: fixable critical vulnerabilities or invalid/incomplete Trivy scan" >&2
  exit 1
fi
echo "Trivy candidate coverage and fixable-critical gate: OK"
