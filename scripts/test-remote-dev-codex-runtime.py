#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("remote-dev-codex-runtime.py")


def load_manager():
    spec = importlib.util.spec_from_file_location("codex_runtime_manager", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.m = load_manager()

    def asset(self):
        target = "x86_64-unknown-linux-musl"
        return {
            "tag": "rust-v0.148.0", "version": "0.148.0", "target": target,
            "name": f"codex-package-{target}.tar.gz",
            "url": f"https://github.com/openai/codex/releases/download/rust-v0.148.0/codex-package-{target}.tar.gz",
            "sha256": "a" * 64, "size": 123,
        }

    def release_metadata(self):
        asset = self.asset()
        return {
            "tag_name": asset["tag"],
            "assets": [{
                "name": asset["name"], "browser_download_url": asset["url"],
                "digest": "sha256:" + asset["sha256"], "size": asset["size"],
            }],
        }

    def package(self, root: Path, version="0.148.0"):
        package = root / "package"
        for directory in ("bin", "codex-path", "codex-resources"):
            (package / directory).mkdir(parents=True, exist_ok=True)
        for rel in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg", "codex-resources/bwrap"):
            path = package / rel
            path.write_bytes(("fake-" + rel).encode())
            path.chmod(0o755)
        (package / "codex-package.json").write_text(json.dumps({
            "layoutVersion": 1, "version": version,
            "target": "x86_64-unknown-linux-musl", "variant": "codex",
            "entrypoint": "bin/codex", "resourcesDir": "codex-resources",
            "pathDir": "codex-path",
        }) + "\n", encoding="utf-8")
        (package / "codex-package.json").chmod(0o644)
        return package

    def test_release_metadata_requires_exact_stable_tag_and_digest(self):
        data = self.release_metadata()
        asset = self.asset()
        with mock.patch.object(self.m, "opener") as opener:
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = self.m.LATEST_URL
            response.read.return_value = json.dumps(data).encode()
            opener.return_value.open.return_value = response
            with mock.patch.object(self.m, "target", return_value=asset["target"]):
                selected = self.m.latest_asset()
        self.assertEqual(selected, asset)

        data["tag_name"] = "rust-v0.149.0-alpha.1"
        with mock.patch.object(self.m, "opener") as opener:
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = self.m.LATEST_URL
            response.read.return_value = json.dumps(data).encode()
            opener.return_value.open.return_value = response
            with self.assertRaisesRegex(self.m.ManagerError, "exact stable"):
                self.m.latest_asset()

    def test_archive_rejects_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("../escape")
                info.size = 1
                output.addfile(info, io.BytesIO(b"x"))
            with self.assertRaisesRegex(self.m.ManagerError, "unsafe"):
                self.m.extract(archive, root / "out")

            archive = root / "link.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("bin/codex")
                info.type = tarfile.SYMTYPE
                info.linkname = "/bin/sh"
                output.addfile(info)
            with self.assertRaisesRegex(self.m.ManagerError, "unsupported"):
                self.m.extract(archive, root / "out2")

    def test_package_metadata_is_exact(self):
        with tempfile.TemporaryDirectory() as text:
            package = self.package(Path(text))
            with mock.patch.object(self.m, "target", return_value=self.asset()["target"]):
                self.assertEqual(self.m.package_metadata(package, self.asset())["version"], "0.148.0")
            data = json.loads((package / "codex-package.json").read_text())
            data["variant"] = "codex-app-server"
            (package / "codex-package.json").write_text(json.dumps(data))
            with mock.patch.object(self.m, "target", return_value=self.asset()["target"]):
                with self.assertRaisesRegex(self.m.ManagerError, "variant"):
                    self.m.package_metadata(package, self.asset())

    def test_newer_runtime_becomes_active_and_tamper_falls_back(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(self.m, "target", return_value=self.asset()["target"]):
                self.m.publish(package, self.asset(), self.asset()["url"])
                with mock.patch.object(self.m, "bundled_version", return_value="0.147.0"):
                    current = self.m.state()
                self.assertEqual(current["kind"], "runtime")
                binary = current["binary"]
                binary.write_bytes(b"tampered")
                binary.chmod(0o700)
                with mock.patch.object(self.m, "bundled_version", return_value="0.147.0"):
                    damaged = self.m.state()
            self.assertEqual(damaged["kind"], "damaged")

    def test_equal_or_older_runtime_never_shadows_bundled(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(self.m, "target", return_value=self.asset()["target"]):
                self.m.publish(package, self.asset(), self.asset()["url"])
                with mock.patch.object(self.m, "bundled_version", return_value="0.148.0"):
                    current = self.m.state()
            self.assertEqual(current["kind"], "bundled-preferred")

    def test_failed_publication_preserves_previous_runtime(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(self.m, "target", return_value=self.asset()["target"]):
                self.m.publish(package, self.asset(), self.asset()["url"])
                previous = (self.m.ROOT / "current").read_text()
                with mock.patch.object(self.m, "records", side_effect=[self.m.records(package), []]):
                    with self.assertRaisesRegex(self.m.ManagerError, "changed while publishing"):
                        self.m.publish(package, self.asset(), self.asset()["url"])
            self.assertEqual((self.m.ROOT / "current").read_text(), previous)

    def test_review_pending_status_is_precise(self):
        current = {"kind": "runtime", "bundled": "0.147.0", "runtime": "0.148.0"}
        with mock.patch("builtins.print") as output:
            self.m.print_status(current, False)
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("official source; Remote Dev review pending", rendered)
        self.assertIn("Codex active source: runtime", rendered)


if __name__ == "__main__":
    unittest.main()
