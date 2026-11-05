#!/usr/bin/env python3
"""Guard the shared host-side fixture contracts without requiring Docker."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_support.antigravity_manager import prepare_manager
from test_support.compose import compose_environment, render_compose
from test_support.context7 import load_module, manager_environment, run_manager


class AntigravityManagerFixtureTests(unittest.TestCase):
    @staticmethod
    def fixture(root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
        manager = root / "production-manager.sh"
        destination = root / "fixture-manager.sh"
        paths = root / "paths with spaces.sh"
        runtime = root / "runtime with spaces.sh"
        lib_dir = root / "fixture runtime"
        lib_dir.mkdir()
        test_bin = root / "test bin"
        (lib_dir / "integrity.sh").write_text(
            "python=/usr/local/lib/remote-dev/python\n", encoding="utf-8"
        )
        manager.write_text(
            "source /usr/local/lib/remote-dev/antigravity-paths.sh\n"
            "source /usr/local/lib/remote-dev/remote-dev-runtime.sh\n"
            "source /usr/local/lib/remote-dev/antigravity-runtime\n"
            "PATH=/opt/remote-dev/mise/shims:/opt/remote-dev/mise/bin:/usr/local/bin:/usr/bin:/bin\n",
            encoding="utf-8",
        )
        return manager, destination, paths, runtime, lib_dir, test_bin

    @staticmethod
    def prepare(paths: tuple[Path, Path, Path, Path, Path, Path]) -> None:
        prepare_manager(*paths, python_executable="/usr/bin/synthetic-python")

    def test_rewrites_only_fixture_files_and_quotes_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remote-dev-agy-manager-test-") as temp:
            paths = self.fixture(Path(temp))
            manager, destination, paths_lib, runtime, lib_dir, test_bin = paths
            original = manager.read_bytes()
            self.prepare(paths)
            rendered = destination.read_text(encoding="utf-8")
            self.assertIn(shlex.quote(str(paths_lib)), rendered)
            self.assertIn(shlex.quote(str(runtime)), rendered)
            self.assertIn(shlex.quote(str(lib_dir)), rendered)
            self.assertIn("PATH=" + shlex.quote(str(test_bin)) + ":", rendered)
            self.assertEqual(manager.read_bytes(), original)
            self.assertEqual(
                (lib_dir / "integrity.sh").read_text(encoding="utf-8"),
                "python=/usr/bin/synthetic-python\n",
            )

    def test_missing_or_duplicate_manager_anchor_fails_without_partial_writes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remote-dev-agy-manager-test-") as temp:
            paths = self.fixture(Path(temp))
            manager, destination, _, _, lib_dir, _ = paths
            integrity = lib_dir / "integrity.sh"
            original_integrity = integrity.read_bytes()
            source = manager.read_text(encoding="utf-8")
            for invalid in (
                source.replace("/usr/local/lib/remote-dev/antigravity-paths.sh", "/bad/path"),
                source + "source /usr/local/lib/remote-dev/antigravity-paths.sh\n",
            ):
                with self.subTest(input=invalid[-40:]):
                    manager.write_text(invalid, encoding="utf-8")
                    with self.assertRaisesRegex(AssertionError, "canonical manager fixture anchor"):
                        self.prepare(paths)
                    self.assertFalse(destination.exists())
                    self.assertEqual(integrity.read_bytes(), original_integrity)

    def test_integrity_python_anchor_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remote-dev-agy-manager-test-") as temp:
            paths = self.fixture(Path(temp))
            _, destination, _, _, lib_dir, _ = paths
            integrity = lib_dir / "integrity.sh"
            integrity.write_text("python=/noncanonical/python\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "canonical manager fixture anchor"):
                self.prepare(paths)
            self.assertFalse(destination.exists())
            self.assertEqual(
                integrity.read_text(encoding="utf-8"), "python=/noncanonical/python\n"
            )


class ComposeFixtureTests(unittest.TestCase):
    def test_environment_is_bounded_and_explicit_overrides_win(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                "HOME": "/synthetic-home",
                "DOCKER_HOST": "unix:///synthetic/docker.sock",
                "COMPOSE_FILE": "/untrusted/compose.yml",
                "COMPOSE_PROJECT_NAME": "untrusted",
                "WEB_PASSWORD": "untrusted-ambient-password",
            },
            clear=True,
        ):
            baseline = compose_environment()
            self.assertEqual(
                baseline,
                {
                    "PATH": "/usr/bin",
                    "HOME": "/synthetic-home",
                    "DOCKER_HOST": "unix:///synthetic/docker.sock",
                },
            )
            overridden = compose_environment({"WEB_PASSWORD": "synthetic-explicit"})
            self.assertEqual(overridden["WEB_PASSWORD"], "synthetic-explicit")
            self.assertNotIn("COMPOSE_FILE", overridden)
            self.assertNotIn("COMPOSE_PROJECT_NAME", overridden)

    def test_renders_multiple_files_with_exact_profile_and_env_file(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"services": {"launcher": {}}}', stderr=""
        )
        with mock.patch("test_support.compose.subprocess.run", return_value=completed) as run:
            result = render_compose(
                Path("/synthetic/repo"),
                (Path("/synthetic/compose.yml"), Path("/synthetic/override.yml")),
                Path("/synthetic/empty.env"),
                {"WEB_PASSWORD": "synthetic-explicit"},
            )
        self.assertEqual(result, {"services": {"launcher": {}}})
        arguments = run.call_args.args[0]
        self.assertEqual(
            arguments,
            [
                "docker", "compose", "--profile", "antigravity",
                "--env-file", "/synthetic/empty.env",
                "-f", "/synthetic/compose.yml",
                "-f", "/synthetic/override.yml",
                "config", "--format", "json",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], Path("/synthetic/repo"))
        self.assertEqual(run.call_args.kwargs["env"]["WEB_PASSWORD"], "synthetic-explicit")
        self.assertFalse(run.call_args.kwargs["check"])

    def test_compose_failure_fails_closed(self) -> None:
        failure = subprocess.CompletedProcess(
            args=[], returncode=42, stdout="", stderr="synthetic invalid configuration"
        )
        with mock.patch("test_support.compose.subprocess.run", return_value=failure):
            with self.assertRaisesRegex(
                AssertionError, "docker compose config failed for /synthetic/compose.yml"
            ):
                render_compose(
                    Path("/synthetic/repo"),
                    Path("/synthetic/compose.yml"),
                    Path("/synthetic/empty.env"),
                )


class Context7FixtureTests(unittest.TestCase):
    def test_codex_home_and_role_are_isolated_from_ambient_environment(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"CODEX_HOME": "/wrong", "REMOTE_DEV_ROLE": "launcher", "HOME": "/synthetic"},
            clear=True,
        ):
            environment = manager_environment(Path("/synthetic/codex"))
            self.assertEqual(environment["CODEX_HOME"], "/synthetic/codex")
            self.assertEqual(environment["REMOTE_DEV_ROLE"], "codex")
            self.assertEqual(environment["HOME"], "/synthetic")
            overridden = manager_environment(
                Path("/synthetic/codex"), {"REMOTE_DEV_ROLE": "launcher"}
            )
            self.assertEqual(overridden["REMOTE_DEV_ROLE"], "launcher")

    def test_module_loading_uses_explicit_source_and_is_not_cached(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remote-dev-ctx7-loader-test-") as temporary:
            path = Path(temporary) / "synthetic_context7_module.py"
            path.write_text("CONTEXT7_FIXTURE_MARKER = 17\n", encoding="utf-8")
            first = load_module(path, module_name="context7_fixture_first")
            second = load_module(path, module_name="context7_fixture_second")
        self.assertEqual(first.CONTEXT7_FIXTURE_MARKER, 17)
        self.assertEqual(second.CONTEXT7_FIXTURE_MARKER, 17)
        self.assertEqual(first.__name__, "context7_fixture_first")
        self.assertEqual(second.__name__, "context7_fixture_second")
        self.assertEqual(first.__file__, str(path))
        self.assertIsNot(first, second)

    def test_module_loader_rejects_unsupported_source(self) -> None:
        with tempfile.TemporaryDirectory(prefix="remote-dev-ctx7-loader-test-") as temporary:
            invalid = Path(temporary) / "synthetic-no-python-extension.txt"
            invalid.write_text("SECRET = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "could not load"):
                load_module(invalid, module_name="context7_fixture_invalid")
            with self.assertRaises(FileNotFoundError):
                load_module(Path(temporary) / "missing.py", module_name="context7_missing")

    def test_subprocess_contract_preserves_input_timeout_and_output(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=3, stdout="synthetic-output", stderr="synthetic-error"
        )
        with mock.patch("test_support.context7.subprocess.run", return_value=completed) as run:
            result = run_manager(
                Path("/synthetic/context7-manager.py"),
                Path("/synthetic/codex"),
                ["install", "--api-key-stdin"],
                input_text="synthetic-key\n",
                extra_env={"SYNTHETIC_NET": "disabled"},
                timeout=30,
            )
        self.assertIs(result, completed)
        self.assertEqual(
            run.call_args.args[0],
            [sys.executable, "/synthetic/context7-manager.py", "install", "--api-key-stdin"],
        )
        arguments = run.call_args.kwargs
        self.assertEqual(arguments["timeout"], 30)
        self.assertEqual(arguments["input"], "synthetic-key\n")
        self.assertEqual(arguments["env"]["CODEX_HOME"], "/synthetic/codex")
        self.assertEqual(arguments["env"]["REMOTE_DEV_ROLE"], "codex")
        self.assertEqual(arguments["env"]["SYNTHETIC_NET"], "disabled")
        self.assertFalse(arguments["check"])

    def test_timeout_propagates_for_caller_specific_handling(self) -> None:
        with mock.patch(
            "test_support.context7.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["synthetic"], 15),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_manager(
                    Path("/synthetic/context7-manager.py"),
                    Path("/synthetic/codex"),
                    ["status"],
                    timeout=15,
                )


if __name__ == "__main__":
    unittest.main()
