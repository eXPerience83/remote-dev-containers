#!/usr/bin/env python3
"""Offline regression coverage for PyPI upstream release-age admission."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "scripts" / "select-mature-pypi-version.py"
spec = importlib.util.spec_from_file_location("select_mature_pypi", SELECTOR)
assert spec is not None and spec.loader is not None
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)

NOW = datetime(2026, 10, 28, 20, 22, tzinfo=timezone.utc)


def pypi_release(
    package: str, version: str, ages: tuple[timedelta, ...],
    *, yanked: bool = False,
) -> dict:
    return {
        "info": {"name": package, "version": version},
        "urls": [
            {
                "filename": f"{package}-{version}-{index}.whl",
                "upload_time_iso_8601": (NOW - age).isoformat(),
                "yanked": yanked,
            }
            for index, age in enumerate(ages)
        ],
    }


class PyPIAgeSelectionTests(unittest.TestCase):
    def select(self, metadata, *, package="pytest", current="9.1.1", candidate="9.2.0"):
        return selector.select_version(
            package=package, current=current, candidate=candidate,
            metadata=metadata, now=NOW,
        )[0]

    def test_recent_pytest_is_deferred(self):
        # Reproduces 2026-10-28: official 9.2.0 uploaded ~22h52m earlier.
        data = pypi_release("pytest", "9.2.0", (timedelta(hours=22, minutes=52),))
        self.assertEqual(self.select(data), "9.1.1")

    def test_eligible_pytest_is_selected_next_day(self):
        data = pypi_release("pytest", "9.2.0", (timedelta(hours=25),))
        self.assertEqual(self.select(data), "9.2.0")

    def test_newest_wheel_controls_cutoff(self):
        data = pypi_release("ruff", "0.17.3", (
            timedelta(hours=26), timedelta(hours=23),
        ))
        self.assertEqual(
            self.select(data, package="ruff", current="0.17.1", candidate="0.17.3"),
            "0.17.1",
        )

    def test_exact_cutoff_is_allowed(self):
        data = pypi_release("pre-commit", "4.7.0", (timedelta(hours=24),))
        self.assertEqual(
            self.select(data, package="pre-commit", current="4.6.0", candidate="4.7.0"),
            "4.7.0",
        )

    def test_unchanged_pin_does_not_require_reselection(self):
        self.assertEqual(self.select({}, candidate="9.1.1"), "9.1.1")

    def test_reject_wrong_project_and_version(self):
        for metadata in (
            pypi_release("evil-pytest", "9.2.0", (timedelta(hours=25),)),
            pypi_release("pytest", "9.3.0", (timedelta(hours=25),)),
        ):
            with self.subTest(metadata=metadata["info"]), self.assertRaises(ValueError):
                self.select(metadata)

    def test_reject_invalid_or_incomplete_metadata(self):
        bad = [
            {"info": {"name": "pytest", "version": "9.2.0"}, "urls": []},
            pypi_release("pytest", "9.2.0", (timedelta(hours=25),), yanked=True),
            {"info": {"name": "pytest", "version": "9.2.0"}, "urls": [
                {"filename": "pytest.whl", "upload_time_iso_8601": "not-a-date"}
            ]},
        ]
        for metadata in bad:
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                self.select(metadata)

    def test_cli_outputs_only_selected_version_to_stdout(self):
        data = pypi_release("pytest", "9.2.0", (timedelta(hours=23),))
        with tempfile.TemporaryDirectory() as tmp:
            metadata = Path(tmp) / "pypi.json"
            metadata.write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SELECTOR), "--package", "pytest",
                 "--current", "9.1.1", "--candidate", "9.2.0",
                 "--metadata", str(metadata)],
                text=True, capture_output=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Live clock is newer than this fixture; stdout must contain a single pin.
        self.assertIn(result.stdout.strip(), {"9.1.1", "9.2.0"})
        self.assertEqual(len(result.stdout.splitlines()), 1)

    def test_updater_wires_all_three_tools_before_lock(self):
        workflow = (ROOT / ".github/workflows/check-upstream.yml").read_text(encoding="utf-8")
        self.assertIn('for spec in RUFF:ruff PYTEST:pytest PRE_COMMIT:pre-commit;', workflow)
        self.assertIn("scripts/select-mature-pypi-version.py", workflow)
        self.assertLess(
            workflow.index("scripts/select-mature-pypi-version.py"),
            workflow.index("MISE_BIN=\"$mise_bin\" bash scripts/regenerate-mise-lock.sh"),
        )
        self.assertIn("24h", SELECTOR.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
