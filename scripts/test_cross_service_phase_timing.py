#!/usr/bin/env python3
"""Guard the eight phase checkpoints in the synthetic isolation smoke test."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/test-cross-service-isolation.sh"
PHASES = (
    "fixture-preparation",
    "initial-role-startup",
    "initial-isolation-and-auth",
    "admin-and-development-tooling",
    "state-canaries-and-authenticated-launcher",
    "codex-recreation",
    "antigravity-recreation",
    "scratch-recreation-and-final-canaries",
)


class IsolationPhaseTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_exactly_one_checkpoint_per_phase_in_order(self) -> None:
        self.assertEqual(
            tuple(re.findall(r'^ci_phase_checkpoint "([^"]+)"$', self.source, re.M)),
            PHASES,
        )

    def test_startup_checkpoint_follows_all_role_health_checks(self) -> None:
        self.assertIn(
            'for name in "$launcher_name" "$codex_name" "$antigravity_name"; do\n'
            '  wait_for_health_command "$name"\n'
            '  assert_image_id "$name"\n'
            'done\n'
            'ci_phase_checkpoint "initial-role-startup"\n',
            self.source,
        )

    def test_timer_uses_bash_builtin_without_extra_processes(self) -> None:
        self.assertIn('ci_phase_started=$SECONDS', self.source)
        self.assertIn('printf \'CI TIMING %s: %ss\\n\'', self.source)
        self.assertIn('ci_phase_started=$SECONDS\n}', self.source)

    def test_final_checkpoint_precedes_success_only(self) -> None:
        self.assertIn(
            'ci_phase_checkpoint "scratch-recreation-and-final-canaries"\n'
            'echo "Hardened cross-service isolation and offline toolchain canaries: OK"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
