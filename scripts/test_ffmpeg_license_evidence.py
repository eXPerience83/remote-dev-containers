#!/usr/bin/env python3
"""Offline tests for verified FFmpeg binary licensing evidence."""
from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("ffmpeg-license-evidence.py")
spec = importlib.util.spec_from_file_location("ffmpeg_license_evidence", SCRIPT)
assert spec is not None and spec.loader is not None
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class FFmpegLicenseEvidenceContract(unittest.TestCase):
    def fixture(self, root: Path):
        browsers = root / "browsers"
        binary = browsers / "ffmpeg_1013/ffmpeg-linux"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"synthetic executable bytes")
        binary.chmod(0o755)
        manifest = {"archives": {
            arch: {"ffmpeg": {"revision": "1013", "sha256": "a" * 64}}
            for arch in ("amd64", "arm64")
        }}
        output = root / "notices/ffmpeg/LICENSE-from-binary.txt"
        return manifest, browsers, output

    @staticmethod
    def synthetic_binary(binary: Path, option: str) -> str:
        if option == "-L":
            return "This FFmpeg build uses the GNU LESSER GENERAL PUBLIC LICENSE.\\n"
        if option == "-version":
            return "ffmpeg version n7-playwright-build-1013 --disable-gpl\\n"
        raise AssertionError("unexpected option")

    def test_emits_notice_from_exact_binary_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, browsers, output = self.fixture(Path(tmp))
            evidence.generate(manifest, browsers, output, "amd64",
                              self.synthetic_binary)
            report = output.read_text()
            self.assertIn("Architecture: amd64", report)
            self.assertIn("Playwright archive revision: 1013", report)
            self.assertIn("Reviewed archive SHA-256: " + "a" * 64, report)
            self.assertIn("Installed executable SHA-256:", report)
            self.assertIn("GNU LESSER GENERAL PUBLIC LICENSE", report)
            self.assertIn("ffmpeg version n7-playwright-build-1013", report)
            self.assertEqual(output.stat().st_mode & 0o777, 0o644)

    def test_missing_binary_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, browsers, output = self.fixture(Path(tmp))
            (browsers / "ffmpeg_1013/ffmpeg-linux").unlink()
            with self.assertRaises(evidence.LicenseEvidenceError):
                evidence.generate(manifest, browsers, output, "amd64",
                                  self.synthetic_binary)
            self.assertFalse(output.exists())

    def test_incoherent_revision_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, browsers, output = self.fixture(Path(tmp))
            manifest["archives"]["arm64"]["ffmpeg"]["revision"] = "1014"
            with self.assertRaises(evidence.LicenseEvidenceError):
                evidence.generate(manifest, browsers, output, "amd64",
                                  self.synthetic_binary)

    def test_empty_or_unidentified_license_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, browsers, output = self.fixture(Path(tmp))
            def bad_licensing(binary, option):
                if option == "-L":
                    return "unknown terms and no clear licensing marker"
                return self.synthetic_binary(binary, option)
            with self.assertRaises(evidence.LicenseEvidenceError):
                evidence.generate(manifest, browsers, output, "amd64", bad_licensing)
            self.assertFalse(output.exists())

    def test_runner_drops_privileges_and_uses_no_agent_env(self):
        with (mock.patch.object(evidence.subprocess, "run",
                                return_value=subprocess.CompletedProcess(
                                    [], 0, stdout="FFmpeg license", stderr="")) as run):
            self.assertEqual(evidence.execute_ffmpeg(Path("/opt/ffmpeg"), "-L"),
                             "FFmpeg license")
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["user"], evidence.UID)
        self.assertEqual(kwargs["group"], evidence.GID)
        self.assertEqual(kwargs["extra_groups"], [])
        self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
        self.assertNotIn("OPENAI_API_KEY", kwargs["env"])


if __name__ == "__main__":
    unittest.main()
