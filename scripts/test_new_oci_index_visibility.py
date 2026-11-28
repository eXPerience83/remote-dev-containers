#!/usr/bin/env python3
"""Only retry an unambiguous missing response for a just-pushed immutable index."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "scripts/resolve-oci-platform-manifest.sh"
REF = "ghcr.io/experience83/remote-dev-base@sha256:" + "1" * 64
CHILD = "ghcr.io/experience83/remote-dev-base@sha256:" + "2" * 64
INDEX = {
    "mediaType": "application/vnd.oci.image.index.v1+json",
    "manifests": [{
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": "sha256:" + "2" * 64,
        "platform": {"os": "linux", "architecture": "amd64"},
    }],
}


class VisibilityTests(unittest.TestCase):
    def run_case(self, scenario, *flags, ref=REF):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {
                "docker": '''#!/usr/bin/env bash
set -euo pipefail
[[ $# == 5 && "$1 $2 $3" == "buildx imagetools inspect" && "$4" == "$EXPECTED_REF" && "$5" == --raw ]] || exit 64
printf '%s\\n' "$4" >> "$CALLS"
n=$(wc -l < "$CALLS")
case "$SCENARIO" in
  transient) (( n > 2 )) || { echo "ERROR: $4: not found" >&2; exit 1; } ;;
  absent) echo "ERROR: $4: not found" >&2; exit 1 ;;
  timeout) echo "ERROR: $4: not found" >&2; exit 124 ;;
  other-status) echo "ERROR: $4: not found" >&2; exit 2 ;;
  unauthorized) echo 'unauthorized: authentication required' >&2; exit 1 ;;
  mixed) printf 'ERROR: %s: not found\\n503 gateway error\\n' "$4" >&2; exit 1 ;;
  other-digest) echo 'ERROR: another digest: not found' >&2; exit 1 ;;
  partial) echo 'partial'; echo "ERROR: $4: not found" >&2; exit 1 ;;
  malformed) echo '{invalid'; exit 0 ;;
  duplicate) cat "$DUPLICATE"; exit 0 ;;
  visible) ;;
  *) exit 64 ;;
esac
cat "$INDEX"
''',
                "sleep": '#!/usr/bin/env bash\nprintf "%s\\n" "$1" >> "$DELAYS"\n',
            }.items():
                path = root / name
                path.write_text(content, encoding="utf-8")
                path.chmod(0o755)
            index = root / "index.json"
            index.write_text(json.dumps(INDEX), encoding="utf-8")
            duplicate = root / "duplicate.json"
            duplicate.write_text(json.dumps(dict(INDEX, manifests=INDEX["manifests"] * 2)), encoding="utf-8")
            calls, delays = root / "calls", root / "delays"
            env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", EXPECTED_REF=REF,
                       SCENARIO=scenario, CALLS=str(calls), DELAYS=str(delays),
                       INDEX=str(index), DUPLICATE=str(duplicate))
            result = subprocess.run(["bash", str(RESOLVER), ref, "linux", "amd64", *flags],
                                    env=env, text=True, capture_output=True, timeout=10)
            return (result, calls.read_text().splitlines() if calls.exists() else [],
                    delays.read_text().splitlines() if delays.exists() else [])

    def test_visible_first_attempt(self):
        result, calls, delays = self.run_case("visible", "--wait-for-push")
        self.assertEqual((result.returncode, result.stdout.strip(), calls, delays), (0, CHILD, [REF], []))

    def test_transient_visibility(self):
        result, calls, delays = self.run_case("transient", "--wait-for-push")
        self.assertEqual((result.returncode, result.stdout.strip(), calls, delays), (0, CHILD, [REF] * 3, ["2", "4"]))

    def test_exhaustion(self):
        result, calls, delays = self.run_case("absent", "--wait-for-push")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((result.stdout, calls, delays), ("", [REF] * 4, ["2", "4", "8"]))

    def test_fail_closed_without_retry(self):
        for scenario in ("timeout", "other-status", "unauthorized", "mixed", "other-digest", "partial", "malformed", "duplicate"):
            with self.subTest(scenario=scenario):
                result, calls, delays = self.run_case(scenario, "--wait-for-push")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((result.stdout, calls, delays), ("", [REF], []))

    def test_default_is_not_retried(self):
        result, calls, delays = self.run_case("absent")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((calls, delays), ([REF], []))

    def test_invalid_arguments_do_not_invoke_registry(self):
        for flags, ref in [(('--unknown',), REF), (('',), REF), (('--wait-for-push',), 'ghcr.io/experience83/remote-dev-base:stable')]:
            with self.subTest(flags=flags, ref=ref):
                result, calls, delays = self.run_case("visible", *flags, ref=ref)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((calls, delays), ([], []))


if __name__ == "__main__":
    unittest.main()
