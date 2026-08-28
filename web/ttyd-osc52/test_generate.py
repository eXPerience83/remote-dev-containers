#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ttyd_osc52_generate", HERE / "generate.py")
generator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(generator)


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.provenance = json.loads((HERE / "provenance.json").read_text())
        request = urllib.request.Request(
            cls.provenance["archive_url"], headers={"User-Agent": "remote-dev-ttyd-osc52-tests"}
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            cls.archive = response.read()

    def repack_header(self, header: bytes) -> bytes:
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as target:
            info = tarfile.TarInfo(self.provenance["html_header_path"])
            info.size = len(header)
            info.mtime = 0
            target.addfile(info, io.BytesIO(header))
        return output.getvalue()

    def test_generation_is_deterministic_and_committed(self) -> None:
        first = generator.generate(self.archive, self.provenance)
        second = generator.generate(self.archive, self.provenance)
        self.assertEqual(first, second)
        self.assertEqual(first, (HERE / "dist" / "index.html").read_bytes())

    def test_archive_drift_fails(self) -> None:
        changed = bytearray(self.archive)
        changed[-1] ^= 1
        with self.assertRaisesRegex(generator.GenerationError, "archive SHA-256"):
            generator.generate(bytes(changed), self.provenance)

    def test_header_drift_fails(self) -> None:
        header = generator.extract_header(self.archive, self.provenance) + b"\n"
        archive = self.repack_header(header)
        provenance = dict(self.provenance, archive_sha256=hashlib.sha256(archive).hexdigest())
        with self.assertRaisesRegex(generator.GenerationError, "src/html.h SHA-256"):
            generator.generate(archive, provenance)

    def test_baseline_drift_fails(self) -> None:
        header = bytearray(generator.extract_header(self.archive, self.provenance))
        position = header.index(b"0xec")
        header[position : position + 4] = b"0xed"
        with self.assertRaises(generator.GenerationError):
            generator.decode_baseline(bytes(header), self.provenance)

    def test_missing_and_ambiguous_anchor_fail(self) -> None:
        for anchor in ("<script data-does-not-exist>", "<"):
            provenance = dict(self.provenance, insertion_anchor=anchor)
            with self.subTest(anchor=anchor), self.assertRaisesRegex(
                generator.GenerationError, "insertion anchor count"
            ):
                generator.generate(self.archive, provenance)

    def test_version_change_requires_issue_174_review(self) -> None:
        self.assertEqual(generator.SUPPORTED_TTYD_VERSION, "1.7.7")
        self.assertEqual(self.provenance["compatibility_issue"], 174)
        self.assertEqual(generator.configured_ttyd_version(), "1.7.7")


if __name__ == "__main__":
    unittest.main()
