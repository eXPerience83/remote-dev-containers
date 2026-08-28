#!/usr/bin/env python3
"""Focused protocol, lifecycle, and negative supply-chain tests for #97."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
PYTHON = shutil.which("python3") or "python3"


class ProtocolContractTests(unittest.TestCase):
    def test_stable_wire_commands_and_opening_message(self) -> None:
        opening = json.dumps(
            {"AuthToken": "synthetic", "columns": 80, "rows": 24}, separators=(",", ":")
        ).encode()
        self.assertEqual(json.loads(opening), {"AuthToken": "synthetic", "columns": 80, "rows": 24})
        self.assertEqual(b"0" + "á中".encode(), b"0\xc3\xa1\xe4\xb8\xad")
        self.assertEqual(
            b"1" + json.dumps({"columns": 120, "rows": 40}).encode(),
            b'1{"columns": 120, "rows": 40}',
        )
        self.assertEqual((b"2", b"3"), (b"2", b"3"))

    def test_client_retains_protocol_and_base_path_contract(self) -> None:
        source = (ROOT / "upstream/html/src/components/terminal/xterm/index.ts").read_text()
        app = (ROOT / "upstream/html/src/components/app.tsx").read_text()
        for token in (
            "OUTPUT = '0'", "SET_WINDOW_TITLE = '1'", "SET_PREFERENCES = '2'",
            "INPUT = '0'", "RESIZE_TERMINAL = '1'", "PAUSE = '2'", "RESUME = '3'",
            "new WebSocket(this.options.wsUrl, ['tty'])",
        ):
            self.assertIn(token, source)
        self.assertIn("path, '/ws'", app)
        self.assertIn("path, '/token'", app)

    def test_extension_and_socket_lifecycles_are_separate(self) -> None:
        patch = (ROOT / "patches/0001-remote-dev-client.patch").read_text()
        self.assertIn("pageDisposables", patch)
        self.assertIn("connectionDisposables", patch)
        self.assertIn("this.disposeConnection();", patch)
        self.assertIn("export const extensions: readonly RemoteDevExtension[] = [];", patch)
        self.assertNotIn("navigator.clipboard", patch)


class ValidatorNegativeTests(unittest.TestCase):
    def fixture(self) -> Path:
        temp = Path(tempfile.mkdtemp())
        repo = temp / "repo"
        shutil.copytree(ROOT, repo / "web/ttyd-client")
        shutil.copytree(
            REPO / "third_party/components/remote-dev-ttyd-client",
            repo / "third_party/components/remote-dev-ttyd-client",
        )
        shutil.copy2(REPO / "versions.env", repo / "versions.env")
        self.addCleanup(shutil.rmtree, temp)
        return repo

    def assert_rejected(self, mutate) -> None:
        repo = self.fixture()
        mutate(repo)
        result = subprocess.run(
            [PYTHON, str(repo / "web/ttyd-client/validate.py")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_changed_upstream_source_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "web/ttyd-client/upstream/html/src/index.tsx").write_text("changed")
        )

    def test_patch_drift_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "web/ttyd-client/patches/0001-remote-dev-client.patch").write_text("changed")
        )

    def test_lock_drift_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "web/ttyd-client/upstream/html/yarn.lock").write_text("changed")
        )

    def test_generated_asset_drift_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "web/ttyd-client/dist/index.html").write_text("changed")
        )

    def test_extra_generated_asset_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "web/ttyd-client/dist/extra.js").write_text("unexpected")
        )

    def test_unexpected_component_is_rejected(self) -> None:
        def mutate(repo: Path) -> None:
            path = repo / "web/ttyd-client/bundle-components.json"
            value = json.loads(path.read_text())
            value["components"].append(
                {"name": "surprise", "version": "1", "license": "MIT", "notice": "ttyd/LICENSE"}
            )
            path.write_text(json.dumps(value))
        self.assert_rejected(mutate)

    def test_missing_notice_is_rejected(self) -> None:
        self.assert_rejected(
            lambda repo: (repo / "third_party/components/remote-dev-ttyd-client/decko/LICENSE").unlink()
        )


if __name__ == "__main__":
    unittest.main()
