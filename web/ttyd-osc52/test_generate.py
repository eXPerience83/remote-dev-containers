#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ttyd_osc52_generate", HERE / "generate.py")
generator = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(generator)

validate_spec = importlib.util.spec_from_file_location("ttyd_osc52_validate", HERE / "validate.py")
validator = importlib.util.module_from_spec(validate_spec)
assert validate_spec.loader is not None
validate_spec.loader.exec_module(validator)


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.provenance = json.loads((HERE / "provenance.json").read_text())
        cls.archive = generator.read_archive(None, cls.provenance)
        cls.components = json.loads((HERE / "bundle-components.json").read_text())
        cls.inventory = json.loads((HERE.parents[1] / "third_party" / "inventory.json").read_text())

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

    def test_downloader_rejects_any_nonexact_upstream_url(self) -> None:
        for url in (
            "file:///tmp/ttyd.tar.gz",
            "http://codeload.github.com/tsl0922/ttyd/tar.gz/40e79c706be14029b391f369bee6613c31667abb",
            "https://github.com/tsl0922/ttyd/archive/40e79c706be14029b391f369bee6613c31667abb.tar.gz",
            "https://codeload.github.com/tsl0922/ttyd/tar.gz/not-the-pinned-commit",
        ):
            provenance = dict(self.provenance, archive_url=url)
            with self.subTest(url=url), self.assertRaisesRegex(generator.GenerationError, "upstream archive URL"):
                generator.read_archive(None, provenance)

    def test_downloader_rejects_redirect_response(self) -> None:
        class RedirectResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def geturl(self):
                return "https://unapproved.example/ttyd.tar.gz"

            def getcode(self):
                return 302

            def read(self):
                return b""

        opener = mock.Mock()
        opener.open.return_value = RedirectResponse()
        with mock.patch.object(generator.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(generator.GenerationError, "response URL"):
                generator.read_archive(None, self.provenance)
        self.assertIsNone(generator.NoRedirectHandler().redirect_request(None, None, 302, "Found", None, "https://bad.example"))

    def test_inventory_record_is_bound_to_provenance_and_components(self) -> None:
        protected = ("id", "source", "version", "license", "image_scope", "notices")
        for field in protected:
            inventory = deepcopy(self.inventory)
            record = next(item for item in inventory["components"] if item["id"] == "remote-dev-ttyd-osc52-client")
            record[field] = "changed" if field != "notices" else []
            with self.subTest(field=field), self.assertRaises(ValueError):
                validator.validate_inventory_record(inventory, self.provenance, self.components)


if __name__ == "__main__":
    unittest.main()
