#!/usr/bin/env python3
"""Guard the eight rootless Antigravity host fixtures and fail-fast batching."""

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/test-cross-service-isolation.sh"
DELIMITER = "ANTIGRAVITY_FIXTURE_BATCH"
FIXTURES = (
    ("Antigravity runtime/admission fixture failed under hardening", "bash", "test-antigravity-runtime-policy-neutral.sh"),
    ("Antigravity security fixture failed under hardening", "bash", "test-antigravity-security-regressions.sh"),
    ("Antigravity repair fixture failed under hardening", "bash", "test-antigravity-repair-download-hardening.sh"),
    ("Antigravity private-staging fixture failed under hardening", "bash", "test-antigravity-staging-wrappers.sh"),
    ("Antigravity installer-origin fixture failed under hardening", "bash", "test-antigravity-redirects.sh"),
    ("Antigravity OAuth fixture failed under hardening", "python", "test-antigravity-oauth.py"),
    ("Antigravity picker fixture failed under hardening", "python", "test-antigravity-picker.py"),
    ("Antigravity resume helper fixture failed under hardening", "bash", "test-run-antigravity-picker.sh"),
)


class AntigravityFixtureBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")
        start = cls.source.split("<<'" + DELIMITER + "'\n", 1)
        assert len(start) == 2, "missing fixture batch heredoc"
        cls.batch, tail = start[1].split("\n" + DELIMITER + "\n", 1)
        assert "docker_exec \"$antigravity_name\" rm -rf" in tail

    def test_shell_syntax(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True, capture_output=True)

    def test_exact_fixture_commands_in_original_order(self) -> None:
        actual = re.findall(
            r'^run_fixture "([^"]+)" \\\n  (bash|python) "\$fixture_root/scripts/([^"]+)"$',
            self.batch,
            re.M,
        )
        self.assertEqual(tuple(actual), FIXTURES)
        self.assertEqual(self.source.count("docker exec -i --user 65534:65534"), 1)
        self.assertNotIn("run_hardened_antigravity_fixture()", self.source)

    def test_rootless_env_timeouts_and_cleanup_preserved(self) -> None:
        for env in ("TMPDIR", "TMP", "TEMP", "UV_CACHE_DIR", "UV_TOOL_DIR",
                    "NPM_CONFIG_CACHE", "PIP_CACHE_DIR", "PRE_COMMIT_HOME"):
            self.assertIn(f'{env}="$fixture_tmp"', self.source)
        self.assertIn('timeout --foreground --kill-after=5s 30s "$@"', self.batch)
        self.assertIn("timeout --foreground --kill-after=5s 270s", self.source)
        self.assertIn('exit "$status"', self.batch)
        self.assertIn('wait_for_health_command "$antigravity_name"', self.source)

    def run_synthetic_batch(
        self, failing_file: str | None = None, slow_file: str | None = None,
        batch: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        with tempfile.TemporaryDirectory(prefix="antigravity-fixture-batch-") as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            trace = root / "trace.txt"
            wrapper_dir = root / "bin"
            wrapper_dir.mkdir()
            python_alias = wrapper_dir / "python"
            python_alias.write_text('#!/bin/sh\nexec "$PYTHON_FOR_BATCH_TEST" "$@"\n')
            python_alias.chmod(0o755)
            for _description, runner, filename in FIXTURES:
                p = scripts / filename
                if runner == "bash":
                    p.write_text(
                        f'printf "%s\\n" "{filename}" >> "$FIXTURE_TRACE"\n'
                        + ("sleep 2\n" if slow_file == filename else "")
                        + ("exit 7\n" if failing_file == filename else "")
                    )
                else:
                    p.write_text(
                        "import os\nfrom pathlib import Path\n"
                        'with Path(os.environ["FIXTURE_TRACE"]).open("a") as trace:\n'
                        f'    trace.write("{filename}\\n")\n'
                        + ("raise SystemExit(7)\n" if failing_file == filename else "")
                    )
            env = os.environ.copy()
            env["FIXTURE_TRACE"] = str(trace)
            env["PYTHON_FOR_BATCH_TEST"] = sys.executable
            env["PATH"] = str(wrapper_dir) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                ["bash", "-s", "--", str(root)],
                input=batch if batch is not None else self.batch,
                text=True, capture_output=True, timeout=15, check=False, env=env,
            )
            observed = trace.read_text().splitlines() if trace.exists() else []
            return result, observed

    def test_all_eight_independent_processes_execute(self) -> None:
        result, observed = self.run_synthetic_batch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(observed, [item[2] for item in FIXTURES])

    def test_failing_fixture_stops_later_processes_and_reports_identity(self) -> None:
        target_index = 5
        description, _runner, target = FIXTURES[target_index]
        result, observed = self.run_synthetic_batch(failing_file=target)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(observed, [item[2] for item in FIXTURES[:target_index + 1]])
        self.assertIn(description, result.stderr)

    def test_per_fixture_timeout_stops_batch(self) -> None:
        # Use a one-second budget only in the synthetic local harness.
        batch = self.batch.replace('--kill-after=5s 30s "$@"',
                                   '--kill-after=5s 1s "$@"')
        self.assertNotEqual(batch, self.batch)
        description, _runner, target = FIXTURES[2]
        result, observed = self.run_synthetic_batch(slow_file=target, batch=batch)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(observed, [item[2] for item in FIXTURES[:3]])
        self.assertIn(description, result.stderr)


if __name__ == "__main__":
    unittest.main()
