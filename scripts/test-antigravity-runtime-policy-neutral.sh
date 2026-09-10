#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT
fixture_root="$temporary/repo"
fixture_scripts="$fixture_root/scripts"
policy_helper="$temporary/remote-dev-antigravity-policy"
mkdir -p "$fixture_scripts/lib"

# The existing lifecycle fixture validates admission, integrity, launch cwd,
# argument preservation and update behavior. Keep that test approval-neutral by
# giving its copied runner a fixture-local guarded policy helper; the dedicated
# approval-policy tests separately validate production mode resolution and the
# autonomous bypass argv.
cp -- "$root/scripts/test-antigravity-runtime.sh" "$fixture_scripts/test-antigravity-runtime.sh"
ln -s -- "$root/scripts/remote-dev-antigravity.sh" "$fixture_scripts/remote-dev-antigravity.sh"
ln -s -- "$root/scripts/lib/remote-dev-runtime.sh" "$fixture_scripts/lib/remote-dev-runtime.sh"
ln -s -- "$root/scripts/lib/antigravity-runtime" "$fixture_scripts/lib/antigravity-runtime"

cat >"$policy_helper" <<'POLICY'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  status|check-guarded)
    printf '%s\n' 'Antigravity guarded compatibility: OK (toolPermission=default, artifactReviewPolicy=default)'
    ;;
  *) exit 2 ;;
esac
POLICY
chmod 0755 "$policy_helper"

python3 - "$root/scripts/run-antigravity.sh" "$fixture_scripts/run-antigravity.sh" "$policy_helper" <<'PY'
from pathlib import Path
import shlex
import sys

source, destination, policy_helper = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
anchor = "readonly policy_helper=/usr/local/bin/remote-dev-antigravity-policy"
if text.count(anchor) != 1:
    raise SystemExit(f"expected one approval-policy fixture anchor: {anchor}")
text = text.replace(
    anchor,
    f"readonly policy_helper={shlex.quote(str(policy_helper))}",
)
destination.write_text(text, encoding="utf-8")
PY
chmod 0755 "$fixture_scripts/run-antigravity.sh"

REMOTE_DEV_ANTIGRAVITY_APPROVAL_MODE=guarded \
  bash "$fixture_scripts/test-antigravity-runtime.sh"
