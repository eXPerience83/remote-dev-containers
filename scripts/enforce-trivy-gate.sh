#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  echo "Usage: $0 <label:report.json> [...]" >&2
  exit 2
fi

findings=0

for entry in "$@"; do
  if [[ "$entry" != *:* ]]; then
    echo "ERROR: invalid Trivy gate argument (expected label:report): $entry" >&2
    exit 2
  fi

  label="${entry%%:*}"
  report="${entry#*:}"

  if [[ -z "$label" || -z "$report" ]]; then
    echo "ERROR: invalid Trivy gate argument (empty label or report): $entry" >&2
    exit 2
  fi
  if [[ ! -s "$report" ]]; then
    echo "ERROR: Trivy report is missing or empty for $label: $report" >&2
    exit 1
  fi
  if ! jq -e 'type == "object"' "$report" >/dev/null; then
    echo "ERROR: Trivy report is not a valid JSON object for $label: $report" >&2
    exit 1
  fi

  fixable_count="$(jq '[
    .Results[]?
    | .Vulnerabilities[]?
    | select(.Severity == "CRITICAL")
    | select((.FixedVersion // "") != "")
  ] | length' "$report")"

  unfixed_count="$(jq '[
    .Results[]?
    | .Vulnerabilities[]?
    | select(.Severity == "CRITICAL")
    | select((.FixedVersion // "") == "")
  ] | length' "$report")"

  if (( fixable_count > 0 )); then
    echo "ERROR: fixable CRITICAL vulnerabilities in $label:" >&2
    jq -r '
      .Results[]? as $result
      | $result.Vulnerabilities[]?
      | select(.Severity == "CRITICAL")
      | select((.FixedVersion // "") != "")
      | "- \(.VulnerabilityID) | \(.PkgName) | \(.InstalledVersion) -> \(.FixedVersion) | \($result.Target)"
    ' "$report" >&2
  else
    echo "No fixable CRITICAL vulnerabilities in $label."
  fi

  if (( unfixed_count > 0 )); then
    echo "$unfixed_count CRITICAL finding(s) without a known fix remain visible in $report."
  fi

  findings=$((findings + fixable_count))
done

if (( findings > 0 )); then
  echo "ERROR: vulnerability gate found $findings fixable CRITICAL finding(s)" >&2
  exit 1
fi
