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


CODEX_RECREATION_SUBPHASES = (
    "restart-and-health",
    "security-and-auth-contract",
    "mise-role-transitions",
    "state-canaries-and-peers",
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

    def test_codex_recreation_subphases_preserve_all_existing_checks(self) -> None:
        start = self.source.index(
            'ci_phase_checkpoint "state-canaries-and-authenticated-launcher"\n'
        )
        end = self.source.index('ci_phase_checkpoint "codex-recreation"\n')
        block = self.source[start:end]
        self.assertIn('ci_codex_recreation_started=$SECONDS\n', block)
        labels = tuple(
            re.findall(r'ci_codex_recreation_checkpoint "([^"]+)"', block)
        )
        self.assertEqual(labels, CODEX_RECREATION_SUBPHASES)
        for original_command, checkpoint in (
            ('assert_image_id "$codex_name"',
             "restart-and-health"),
            ('assert_read_only_rootfs "$codex_name" Codex',
             "security-and-auth-contract"),
            ('assert_mise_trust_state "$codex_name" observe untrusted',
             "mise-role-transitions"),
            ('wait_for_health_command "$antigravity_name"',
             "state-canaries-and-peers"),
        ):
            self.assertIn(
                original_command + '\n'
                + 'ci_codex_recreation_checkpoint "' + checkpoint + '"',
                block,
            )
        self.assertEqual(
            len(re.findall(r'^assert_mise_trust_state ', block, re.M)), 5
        )
        self.assertIn('verify_canaries codex_invariants "$codex_name"', block)
        self.assertIn(
            'verify_canaries antigravity_invariants "$antigravity_name"',
            block,
        )

    def test_codex_subphase_timer_is_independent_and_uses_bash_seconds(self) -> None:
        function = self.source.split(
            'ci_codex_recreation_checkpoint() {\n', 1
        )[1].split('\n}', 1)[0]
        self.assertIn('SECONDS - ci_codex_recreation_started', function)
        self.assertIn('ci_codex_recreation_started=$SECONDS', function)
        self.assertIn('CI TIMING codex-recreation/%s: %ss', function)
        self.assertNotIn('ci_phase_started=', function)
        self.assertNotIn('ci_admin_subphase_started=', function)

    def test_mise_diffs_fail_closed_and_report_independent_costs(self) -> None:
        function = self.source.split(
            'assert_mise_trust_state() {\n', 1
        )[1].split('\n}', 1)[0]
        self.assertEqual(function.count('docker diff "$name"'), 2)
        self.assertIn('|| fail "native mise $role $action/$expected pre-action docker diff failed"', function)
        self.assertIn('|| fail "native mise $role $action/$expected post-action docker diff failed"', function)
        self.assertIn('"$rootfs_before" "$rootfs_after"', function)
        self.assertIn('CI TIMING mise-trust-state/%s/%s/%s:', function)
        self.assertIn('before-diff=%ss exec=%ss after-diff=%ss', function)
        self.assertNotIn('ci_phase_started=', function)
        self.assertNotIn('ci_codex_recreation_started=', function)

    def test_final_checkpoint_precedes_success_only(self) -> None:
        self.assertIn(
            'ci_phase_checkpoint "scratch-recreation-and-final-canaries"\n'
            'echo "Hardened cross-service isolation and offline toolchain canaries: OK"',
            self.source,
        )


if __name__ == "__main__":
    unittest.main()
