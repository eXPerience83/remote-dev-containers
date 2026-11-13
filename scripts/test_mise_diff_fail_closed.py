#!/usr/bin/env python3
"""Exercise the real mise rootfs guard with synthetic, controlled Docker failures."""

from pathlib import Path
import os
import shlex
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("test-cross-service-isolation.sh")


class MiseDiffFailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        cls.function = source.split(
            "assert_mise_trust_state() {\n", 1
        )[1].split("\n}\n", 1)[0]

    def _check(
        self, scenario: str
    ) -> tuple[subprocess.CompletedProcess[str], int]:
        with tempfile.TemporaryDirectory(prefix="mise-diff-synthetic-") as directory:
            calls = Path(directory) / "diff-calls"
            calls.write_text("", encoding="utf-8")
            # Docker exec is a deliberately inert stub. Only the original Bash
            # outer assertion and its two docker-diff guards are exercised.
            harness = (
                "set -euo pipefail\n"
                "codex_name=fixture-codex\n"
                "antigravity_name=fixture-antigravity\n"
                "DIFF_CALLS=" + shlex.quote(str(calls)) + "\n"
                + r'''
docker() {
  test "$1" = diff || exit 91
  local count
  count="$(wc -l < "$DIFF_CALLS")"
  printf 'call\n' >> "$DIFF_CALLS"
  case "$FAKE_SCENARIO:$count" in
    pre_fail:0|post_fail:1) return 45 ;;
    mismatch:1) printf 'C /unexpected-rootfs-change\n' ;;
  esac
}
docker_exec() { return 0; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 7; }
assert_equal() { [[ "$2" == "$3" ]] || fail "$1"; }
assert_mise_trust_state() {
'''
                + self.function
                + "\n}\nassert_mise_trust_state fixture-codex observe trusted\n"
            )
            environment = os.environ.copy()
            environment["FAKE_SCENARIO"] = scenario
            result = subprocess.run(
                ["bash", "-s"],
                input=harness,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
                env=environment,
            )
            return result, len(calls.read_text(encoding="utf-8").splitlines())

    def test_successful_empty_read_only_rootfs_snapshots_are_valid(self) -> None:
        result, calls = self._check("ok")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, 2)
        self.assertRegex(
            result.stdout,
            r"^CI TIMING mise-trust-state/codex/observe/trusted: "
            r"before-diff=\d+s exec=\d+s after-diff=\d+s\n$",
        )

    def test_pre_action_docker_diff_error_fails_before_exec(self) -> None:
        result, calls = self._check("pre_fail")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, 1)
        self.assertIn("pre-action docker diff failed", result.stderr)

    def test_post_action_docker_diff_error_cannot_pass_on_empty_output(self) -> None:
        result, calls = self._check("post_fail")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, 2)
        self.assertIn("post-action docker diff failed", result.stderr)

    def test_actual_rootfs_difference_remains_a_hard_failure(self) -> None:
        result, calls = self._check("mismatch")
        self.assertEqual(result.returncode, 7)
        self.assertEqual(calls, 2)
        self.assertIn("mise action rootfs changes", result.stderr)

    def test_original_role_assertion_has_no_unchecked_nested_diff(self) -> None:
        self.assertEqual(self.function.count('docker diff "$name"'), 2)
        self.assertNotRegex(
            self.function,
            r'assert_equal .*"\$\(\s*docker diff',
        )
        for expected in ("prepare", "observe", "trust", "untrust"):
            self.assertIn(expected, self.function)


if __name__ == "__main__":
    unittest.main()
