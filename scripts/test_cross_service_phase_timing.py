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

    def test_admin_subphases_follow_all_existing_assertions(self) -> None:
        before, separator, tail = self.source.partition(
            'ci_phase_checkpoint "initial-isolation-and-auth"'
        )
        self.assertTrue(separator)
        admin_block, separator, after = tail.partition(
            'ci_phase_checkpoint "admin-and-development-tooling"'
        )
        self.assertTrue(separator)
        self.assertIn('ci_admin_subphase_started=$SECONDS', admin_block)
        self.assertNotIn("ci_admin_subphase_checkpoint", before)
        self.assertNotIn("ci_admin_subphase_checkpoint", after)
        self.assertEqual(
            tuple(
                re.findall(
                    r'^\\s*ci_admin_subphase_checkpoint "([^"]+)"
        self.assertIn(
            'ci_phase_checkpoint "scratch-recreation-and-final-canaries"\n'
            'echo "Hardened cross-service isolation and offline toolchain canaries: OK"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
,
                    admin_block,
                    re.M,
                )
            ),
            ADMIN_SUBPHASES,
        )
        for assertion, label in (
            ('assert_project_toolchain_workflow "$codex_name" Codex', "project-toolchain-codex"),
            ('assert_project_toolchain_workflow "$antigravity_name" Antigravity', "project-toolchain-antigravity"),
            ("assert_hardened_codex_runtime_regressions", "codex-runtime-regressions"),
            ("assert_hardened_antigravity_host_fixtures", "antigravity-host-fixtures"),
            ('assert_mise_trust_state "$antigravity_name" observe untrusted', "mise-trust-state"),
        ):
            self.assertIn(
                f'{assertion}\\nci_admin_subphase_checkpoint "{label}"',
                admin_block,
            )
        self.assertIn(
            'if [[ "$admin_role_container" == "$codex_name" ]]; then\\n'
            '    ci_admin_subphase_checkpoint "administrative-python-codex"\\n'
            '  else\\n'
            '    ci_admin_subphase_checkpoint "administrative-python-antigravity"',
            admin_block,
        )

    def test_admin_timer_is_independent_of_outer_phases(self) -> None:
        timer = self.source.split("ci_admin_subphase_checkpoint() {", 1)[1].split(
            "}\\n", 1
        )[0]
        self.assertIn("SECONDS - ci_admin_subphase_started", timer)
        self.assertIn("ci_admin_subphase_started=$SECONDS", timer)
        self.assertIn("CI TIMING admin-and-development-tooling/%s: %ss", timer)
        self.assertNotIn("ci_phase_started=", timer)

    def test_final_checkpoint_precedes_success_only(self) -> None:
        self.assertIn(
            'ci_phase_checkpoint "scratch-recreation-and-final-canaries"\n'
            'echo "Hardened cross-service isolation and offline toolchain canaries: OK"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
