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


ADMIN_SUBPHASES = (
    "administrative-python-codex",
    "administrative-python-antigravity",
    "project-toolchain-codex",
    "project-toolchain-antigravity",
    "codex-runtime-regressions",
    "antigravity-host-fixtures",
    "mise-trust-state",
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

    def test_admin_subphases_stay_inside_existing_phase_in_order(self) -> None:
        start = self.source.index('ci_phase_checkpoint "initial-isolation-and-auth"\n')
        end = self.source.index('ci_phase_checkpoint "admin-and-development-tooling"\n')
        block = self.source[start:end]
        self.assertIn('ci_admin_subphase_started=$SECONDS\n', block)
        labels = tuple(re.findall(r'ci_admin_subphase_checkpoint "([^"]+)"', block))
        self.assertEqual(labels, ADMIN_SUBPHASES)
        self.assertIn(
            'assert_project_toolchain_workflow "$codex_name" Codex\n'
            'ci_admin_subphase_checkpoint "project-toolchain-codex"',
            block,
        )
        self.assertIn(
            'assert_project_toolchain_workflow "$antigravity_name" Antigravity\n'
            'ci_admin_subphase_checkpoint "project-toolchain-antigravity"',
            block,
        )
        self.assertIn(
            'assert_hardened_codex_runtime_regressions\n'
            'ci_admin_subphase_checkpoint "codex-runtime-regressions"',
            block,
        )
        self.assertIn(
            'assert_hardened_antigravity_host_fixtures\n'
            'ci_admin_subphase_checkpoint "antigravity-host-fixtures"',
            block,
        )
        self.assertIn(
            'assert_mise_trust_state "$antigravity_name" observe untrusted\n'
            'ci_admin_subphase_checkpoint "mise-trust-state"',
            block,
        )

    def test_admin_timer_uses_builtin_without_resetting_outer_timer(self) -> None:
        function = self.source.split('ci_admin_subphase_checkpoint() {\n', 1)[1]
        function = function.split('\n}', 1)[0]
        self.assertIn('SECONDS - ci_admin_subphase_started', function)
        self.assertIn('ci_admin_subphase_started=$SECONDS', function)
        self.assertIn('CI TIMING admin-and-development-tooling/%s: %ss', function)
        self.assertNotIn('ci_phase_started=', function)

    def test_final_checkpoint_precedes_success_only(self) -> None:
        self.assertIn(
            'ci_phase_checkpoint "scratch-recreation-and-final-canaries"\n'
            'echo "Hardened cross-service isolation and offline toolchain canaries: OK"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
