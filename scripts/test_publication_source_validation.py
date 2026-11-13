#!/usr/bin/env python3
"""Regression contract for the shared publication source preflight."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate-publication-source.sh"
WORKFLOWS = {
    "stable": ".github/workflows/publish-amd64.yml",
    "edge": ".github/workflows/publish-edge-amd64.yml",
    "candidate": ".github/workflows/publish-pr-candidate-worker-amd64.yml",
}
PREVALIDATION_HEADER = "      - name: Validate repository configuration\n        run: |\n"


class SourceValidationTests(unittest.TestCase):
    def test_script_shell_syntax(self) -> None:
        result = subprocess.run(
            ["/bin/bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=5
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_publisher_calls_exact_shared_preflight(self) -> None:
        for mode, filename in WORKFLOWS.items():
            with self.subTest(mode=mode):
                source = (ROOT / filename).read_text(encoding="utf-8")
                self.assertEqual(source.count(PREVALIDATION_HEADER), 1)
                block = source.split(PREVALIDATION_HEADER, 1)[1].split("\n      - ", 1)[0]
                self.assertEqual(
                    block.strip(), f"bash scripts/validate-publication-source.sh {mode}"
                )

    def test_invalid_modes_fail_before_running_any_command(self) -> None:
        for args in ([], ["other"], ["stable", "edge"], [""]):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["/bin/bash", str(SCRIPT), *args],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage:" if len(args) != 1 else "unsupported", result.stderr)

    def fixture(self, root: Path) -> Path:
        (root / "scripts").mkdir()
        (root / "scripts/fixture.sh").write_text("#!/bin/bash\nexit 0\n")
        (root / "compose").mkdir()
        (root / "compose/one.yml").write_text("services: {}\n")
        (root / "compose/two.yml").write_text("services: {}\n")
        (root / "renovate.json").write_text("{}\n")
        bin_dir = root / "fakebin"
        bin_dir.mkdir()
        wrapper = """#!/bin/sh
printf '%s|%s\\n' "$0" "$*" >> "$CAPTURE"
if [ -n "$FAIL_ARGUMENT" ]; then
    case "$*" in
        *"$FAIL_ARGUMENT"*) exit 39 ;;
    esac
fi
"""
        for command in ("bash", "python3", "jq", "docker"):
            target = bin_dir / command
            target.write_text(wrapper)
            target.chmod(0o755)
        return bin_dir

    def run_fixture(
        self, root: Path, fakebin: Path, mode: str, *, fail_argument: str = ""
    ) -> tuple[subprocess.CompletedProcess[str], list[tuple[str, str]]]:
        capture = root / "captured"
        env = dict(
            os.environ,
            PATH=f"{fakebin}:/usr/bin:/bin",
            CAPTURE=str(capture),
            FAIL_ARGUMENT=fail_argument,
        )
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), mode],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        calls = []
        if capture.exists():
            for entry in capture.read_text().splitlines():
                binary, args = entry.split("|", 1)
                calls.append((Path(binary).name, args))
        return result, calls

    def test_exact_commands_per_mode_and_compose_difference(self) -> None:
        common = [
            ("bash", "-n scripts/fixture.sh"),
            ("bash", "scripts/test-image-name-compat.sh"),
            ("bash", "scripts/test-image-identity.sh"),
            ("python3", "scripts/test_edge_build_identity.py"),
            ("python3", "scripts/test_update_upstream_changelog.py"),
            ("bash", "scripts/validate-version-pins.sh"),
            ("bash", "scripts/test-source-revision.sh"),
            ("jq", "-e . renovate.json"),
            ("python3", "scripts/validate-renovate-ownership.py --root ."),
        ]
        compose = [
            ("docker", "compose -f compose/one.yml config --quiet"),
            ("docker", "compose -f compose/two.yml config --quiet"),
        ]
        for mode in WORKFLOWS:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                fakebin = self.fixture(root)
                result, calls = self.run_fixture(root, fakebin, mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, common + ([] if mode == "stable" else compose))
                self.assertEqual(
                    result.stdout.splitlines(),
                    [] if mode == "stable" else ["OK compose/one.yml", "OK compose/two.yml"],
                )

    def test_first_failure_aborts_before_later_guards_or_compose(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            fakebin = self.fixture(root)
            result, calls = self.run_fixture(
                root, fakebin, "edge", fail_argument="scripts/validate-version-pins.sh"
            )
            self.assertEqual(result.returncode, 39, result.stderr)
            self.assertEqual(calls[-1], ("bash", "scripts/validate-version-pins.sh"))
            self.assertFalse(any(command == "docker" for command, _ in calls))
            self.assertNotIn(("bash", "scripts/test-source-revision.sh"), calls)


if __name__ == "__main__":
    unittest.main()
