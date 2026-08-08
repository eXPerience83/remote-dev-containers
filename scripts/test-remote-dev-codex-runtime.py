#!/usr/bin/env python3
from __future__ import annotations

import contextlib
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
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CodexRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.m = load_manager()

    def asset(self, version: str = "0.148.0", sha: str | None = None):
        target = "x86_64-unknown-linux-musl"
        digest = sha or "a" * 64
        return {
            "tag": f"rust-v{version}",
            "version": version,
            "target": target,
            "name": f"codex-package-{target}.tar.gz",
            "url": (
                f"https://github.com/openai/codex/releases/download/rust-v{version}/"
                f"codex-package-{target}.tar.gz"
            ),
            "sha256": digest,
            "size": 123,
        }

    def release_metadata(self):
        asset = self.asset()
        return {
            "tag_name": asset["tag"],
            "assets": [
                {
                    "name": asset["name"],
                    "browser_download_url": asset["url"],
                    "digest": "sha256:" + asset["sha256"],
                    "size": asset["size"],
                }
            ],
        }

    def package(self, root: Path, version: str = "0.148.0"):
        package = root / f"package-{version}"
        for directory in ("bin", "codex-path", "codex-resources"):
            (package / directory).mkdir(parents=True, exist_ok=True)
        for rel in (
            "bin/codex",
            "bin/codex-code-mode-host",
            "codex-path/rg",
            "codex-resources/bwrap",
        ):
            path = package / rel
            path.write_bytes(("fake-" + rel + "-" + version).encode())
            path.chmod(0o755)
        metadata = {
            "layoutVersion": 1,
            "version": version,
            "target": "x86_64-unknown-linux-musl",
            "variant": "codex",
            "entrypoint": "bin/codex",
            "resourcesDir": "codex-resources",
            "pathDir": "codex-path",
        }
        metadata_path = package / "codex-package.json"
        metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        metadata_path.chmod(0o644)
        return package

    def test_release_metadata_requires_exact_stable_tag_and_digest(self):
        data = self.release_metadata()
        asset = self.asset()
        with mock.patch.object(self.m, "opener") as opener, mock.patch.object(
            self.m, "target", return_value=asset["target"]
        ):
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = self.m.LATEST_URL
            response.read.return_value = json.dumps(data).encode()
            opener.return_value.open.return_value = response
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
            with mock.patch.object(
                self.m, "target", return_value=self.asset()["target"]
            ):
                self.assertEqual(
                    self.m.package_metadata(package, self.asset())["version"],
                    "0.148.0",
                )
            metadata_path = package / "codex-package.json"
            data = json.loads(metadata_path.read_text())
            data["variant"] = "codex-app-server"
            metadata_path.write_text(json.dumps(data))
            with mock.patch.object(
                self.m, "target", return_value=self.asset()["target"]
            ), self.assertRaisesRegex(self.m.ManagerError, "variant"):
                self.m.package_metadata(package, self.asset())

    def test_newer_runtime_becomes_active_and_tamper_falls_back(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(
                self.m, "target", return_value=self.asset()["target"]
            ):
                self.m.publish(package, self.asset(), self.asset()["url"])
                with mock.patch.object(
                    self.m, "bundled_version", return_value="0.147.0"
                ):
                    current = self.m.state()
                self.assertEqual(current["kind"], "runtime")
                binary = current["binary"]
                binary.write_bytes(b"tampered")
                binary.chmod(0o700)
                with mock.patch.object(
                    self.m, "bundled_version", return_value="0.147.0"
                ):
                    damaged = self.m.state()
            self.assertEqual(damaged["kind"], "damaged")

    def test_dangling_current_symlink_is_damaged(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "runtime"
            self.m.ROOT.mkdir()
            (self.m.ROOT / "current").symlink_to("missing")
            with mock.patch.object(self.m, "bundled_version", return_value="0.147.0"):
                current = self.m.state()
            self.assertEqual(current["kind"], "damaged")

    def test_equal_or_older_runtime_never_shadows_bundled(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(
                self.m, "target", return_value=self.asset()["target"]
            ):
                self.m.publish(package, self.asset(), self.asset()["url"])
                with mock.patch.object(
                    self.m, "bundled_version", return_value="0.148.0"
                ):
                    current = self.m.state()
            self.assertEqual(current["kind"], "bundled-preferred")

    def test_failed_publication_preserves_previous_runtime(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            with mock.patch.object(
                self.m, "target", return_value=self.asset()["target"]
            ):
                self.m.publish(package, self.asset(), self.asset()["url"])
                previous = (self.m.ROOT / "current").read_text()
                first_records = self.m.records(package)
                with mock.patch.object(
                    self.m, "records", side_effect=[first_records, []]
                ), self.assertRaisesRegex(
                    self.m.ManagerError, "changed while publishing"
                ):
                    self.m.publish(package, self.asset(), self.asset()["url"])
            self.assertEqual((self.m.ROOT / "current").read_text(), previous)

    def test_successful_publication_retains_previous_generation(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "runtime"
            first_asset = self.asset("0.148.0", "a" * 64)
            second_asset = self.asset("0.149.0", "b" * 64)
            with mock.patch.object(
                self.m, "target", return_value=first_asset["target"]
            ):
                self.m.publish(
                    self.package(root, "0.148.0"), first_asset, first_asset["url"]
                )
                previous_name = (self.m.ROOT / "current").read_text().strip()
                self.m.publish(
                    self.package(root, "0.149.0"), second_asset, second_asset["url"]
                )
            current_name = (self.m.ROOT / "current").read_text().strip()
            releases = self.m.ROOT / "releases"
            self.assertNotEqual(previous_name, current_name)
            self.assertTrue((releases / previous_name).is_dir())
            self.assertTrue((releases / current_name).is_dir())

    def test_resolve_selects_runtime_only_for_runtime_state(self):
        runtime_binary = Path("/private/runtime/bin/codex")
        cases = (
            ({"kind": "runtime", "binary": runtime_binary}, str(runtime_binary)),
            ({"kind": "bundled", "bundled": "0.147.0"}, str(self.m.BUNDLED)),
            (
                {
                    "kind": "bundled-preferred",
                    "bundled": "0.148.0",
                    "runtime": "0.147.0",
                },
                str(self.m.BUNDLED),
            ),
            (
                {
                    "kind": "damaged",
                    "bundled": "0.147.0",
                    "warning": "tampered",
                },
                str(self.m.BUNDLED),
            ),
        )
        for current, expected in cases:
            with self.subTest(kind=current["kind"]), mock.patch.object(
                self.m, "state", return_value=current
            ):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(self.m.main(["resolve"]), 0)
                self.assertEqual(stdout.getvalue().strip(), expected)
                if current["kind"] == "damaged":
                    self.assertIn("bundled fallback", stderr.getvalue())

    def test_remove_deletes_only_optional_runtime(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "runtime"
            bundled = root / "bundled-codex"
            bundled.write_bytes(b"immutable bundled bytes")
            bundled.chmod(0o755)
            self.m.BUNDLED = bundled
            asset = self.asset()
            with mock.patch.object(self.m, "target", return_value=asset["target"]):
                self.m.publish(self.package(root), asset, asset["url"])
                before = bundled.read_bytes()
                self.m.remove_runtime(yes=True)
            self.assertEqual(bundled.read_bytes(), before)
            self.assertFalse((self.m.ROOT / "current").exists())
            self.assertEqual(list((self.m.ROOT / "releases").iterdir()), [])

    def test_status_and_resolve_never_open_network(self):
        with tempfile.TemporaryDirectory() as text:
            self.m.ROOT = Path(text) / "missing-runtime"
            with mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ), mock.patch.object(
                self.m, "opener", side_effect=AssertionError("network used")
            ):
                for command in (["status"], ["resolve"]):
                    with self.subTest(command=command[0]):
                        stdout = io.StringIO()
                        with contextlib.redirect_stdout(stdout):
                            self.assertEqual(self.m.main(command), 0)
                        self.assertTrue(stdout.getvalue().strip())

    def test_update_requires_confirmation_before_network(self):
        with mock.patch.object(
            self.m, "bundled_version", return_value="0.147.0"
        ), mock.patch.object(
            self.m,
            "state",
            return_value={"kind": "bundled", "bundled": "0.147.0"},
        ), mock.patch.object(
            self.m, "latest_asset"
        ) as latest_asset, mock.patch.object(
            self.m.sys.stdin, "isatty", return_value=False
        ):
            with self.assertRaisesRegex(self.m.ManagerError, "interactive confirmation"):
                self.m.update_runtime(yes=False)
        latest_asset.assert_not_called()

    def test_review_pending_status_is_precise(self):
        current = {"kind": "runtime", "bundled": "0.147.0", "runtime": "0.148.0"}
        with mock.patch("builtins.print") as output:
            self.m.print_status(current, menu=False)
        rendered = "\n".join(str(call.args[0]) for call in output.call_args_list)
        self.assertIn("official source; Remote Dev review pending", rendered)
        self.assertIn("Codex active source: runtime", rendered)


if __name__ == "__main__":
    unittest.main()
