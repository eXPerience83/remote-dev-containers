#!/usr/bin/env python3
"""Regression: neither Python legal CLI may write to an ambiguous output tree."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = (
    "compact-python-runtime-notices.py",
    "sync-python-runtime-notices.py",
)


class PythonNoticeTargetGuardTests(unittest.TestCase):
    def test_mismatched_and_ambiguous_outputs_fail_before_writes(self) -> None:
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix="python-notice-path-guard-") as tmp:
            root = Path(tmp)
            components = root / "third_party/components"
            default = components / "python-build-standalone"
            secondary = components / "python-build-standalone-315"
            custom = components / "temporary-standalone"
            for target in (default, secondary, custom):
                for arch in ("amd64", "arm64"):
                    folder = target / arch
                    folder.mkdir(parents=True)
                    (folder / "PYTHON.json").write_text(
                        '{"python_version":"3.15.0",'
                        '"target_triple":"x86_64-unknown-linux-gnu",'
                        '"license_path":"licenses/LICENSE.cpython.txt",'
                        '"licenses":["Python-2.0"],'
                        '"build_info":{"extensions":{}}}\n',
                        encoding="utf-8",
                    )
                    (folder / "marker").write_text("preserve\n", encoding="utf-8")
            for script in SCRIPTS:
                for mode in ("--write", "--check"):
                    for label, output, explicit in (
                        ("secondary unspecified", secondary, None),
                        ("secondary wrong 3.14", secondary, "3.14.8"),
                        ("default wrong 3.15", default, "3.15.0"),
                        ("custom unspecified", custom, None),
                    ):
                        with self.subTest(script=script, mode=mode, case=label):
                            before = {
                                str(p.relative_to(output)): p.read_bytes()
                                for p in output.rglob("*") if p.is_file()
                            }
                            cmd = [
                                sys.executable, str(scripts / script),
                                mode, "--root", str(root),
                                "--output", str(output),
                            ]
                            if explicit:
                                cmd += ["--python-version", explicit]
                            result = subprocess.run(
                                cmd, capture_output=True, text=True,
                                check=False, timeout=12,
                            )
                            self.assertEqual(
                                result.returncode, 2,
                                f"{script} {label}: {result.stderr[-900:]}",
                            )
                            self.assertIn("error:", result.stderr)
                            after = {
                                str(p.relative_to(output)): p.read_bytes()
                                for p in output.rglob("*") if p.is_file()
                            }
                            self.assertEqual(after, before, "legal evidence was modified")

    def test_explicit_version_allows_other_output_and_matching_tree(self) -> None:
        # Do not download anything: validate the shared pre-I/O target contract.
        import importlib.util
        script = Path(__file__).with_name("sync-python-runtime-notices.py")
        spec = importlib.util.spec_from_file_location("notice_sync_guard", script)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parser = argparse.ArgumentParser()
        with tempfile.TemporaryDirectory(prefix="python-notice-explicit-") as tmp:
            root = Path(tmp)
            default = root / "third_party/components/python-build-standalone"
            secondary = root / "third_party/components/python-build-standalone-315"
            scratch = root / "scratch"
            for target, version in (
                (default, None),
                (default, "3.14.8"),
                (secondary, "3.15.0"),
                (scratch, "3.15.0"),
            ):
                module.validate_notice_target(root, target, version, parser)


if __name__ == "__main__":
    unittest.main()
