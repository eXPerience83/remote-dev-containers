#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("remote-dev-codex-runtime.py")
DOCTOR = Path(__file__).with_name("remote-dev-doctor.sh")
if not DOCTOR.is_file():
    DOCTOR = Path("/usr/local/bin/remote-dev-doctor")


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

    def latest_asset_from(self, data):
        asset = self.asset()
        with mock.patch.object(self.m, "opener") as opener, mock.patch.object(
            self.m, "target", return_value=asset["target"]
        ):
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.geturl.return_value = self.m.LATEST_URL
            response.read.return_value = json.dumps(data).encode()
            opener.return_value.open.return_value = response
            return self.m.latest_asset()

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

    def staging_root(self, root: Path) -> Path:
        root.chmod(0o711)
        run = root / "run"
        run.mkdir(mode=0o711)
        run.chmod(0o711)
        return run / "remote-dev-codex-update"

    def publish_fixture(self, root: Path, version: str = "0.148.0"):
        asset = self.asset(version)
        self.m.ROOT = root / "runtime"
        with mock.patch.object(self.m, "target", return_value=asset["target"]):
            self.m.publish(self.package(root, version), asset, asset["url"])
        name = (self.m.ROOT / "current").read_text(encoding="utf-8").strip()
        release = self.m.ROOT / "releases" / name
        return asset, release, release / "package"

    def runtime_state(self, bundled: str = "0.147.0"):
        with mock.patch.object(self.m, "bundled_version", return_value=bundled):
            return self.m.state()

    def test_release_metadata_requires_exact_stable_tag_and_digest(self):
        data = self.release_metadata()
        self.assertEqual(self.latest_asset_from(data), self.asset())

        data = self.release_metadata()
        data["tag_name"] = "rust-v0.149.0-alpha.1"
        with self.assertRaisesRegex(self.m.ManagerError, "exact stable"):
            self.latest_asset_from(data)

        invalid_cases = (
            ("digest without prefix", "digest", "a" * 64, "SHA-256"),
            ("non-hex digest", "digest", "sha256:" + "g" * 64, "SHA-256"),
            ("zero size", "size", 0, "invalid/excessive size"),
            (
                "oversized package",
                "size",
                self.m.MAX_PACKAGE + 1,
                "invalid/excessive size",
            ),
        )
        for label, field, value, message in invalid_cases:
            with self.subTest(case=label):
                invalid = self.release_metadata()
                invalid["assets"][0][field] = value
                with self.assertRaisesRegex(self.m.ManagerError, message):
                    self.latest_asset_from(invalid)

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

    def test_extract_normalizes_implicit_directories_under_umask_077(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            root.chmod(0o711)
            archive = root / "candidate.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                content = b"#!/bin/sh\nexit 0\n"
                info = tarfile.TarInfo("bin/implicit/codex")
                info.mode = 0o755
                info.size = len(content)
                output.addfile(info, io.BytesIO(content))

            previous_umask = os.umask(0o077)
            try:
                package = root / "package"
                self.m.extract(archive, package)
            finally:
                os.umask(previous_umask)

            for directory in (package, package / "bin", package / "bin/implicit"):
                info = directory.stat()
                self.assertEqual(info.st_uid, os.geteuid())
                self.assertEqual(info.st_mode & 0o777, 0o755)
            candidate = package / "bin/implicit/codex"
            self.assertEqual(candidate.stat().st_mode & 0o777, 0o755)
            self.m.require_candidate_path(candidate, executable=True)

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

    def test_legacy_runtime_full_hashes_once_then_uses_fast_path(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            self.m.stamp_path().unlink()
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                current = self.runtime_state()
                self.assertEqual(current["kind"], "runtime")
                self.assertGreater(file_sha.call_count, 0)
            self.assertTrue(self.m.stamp_path().is_file())

            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                current = self.runtime_state()
                self.assertEqual(current["kind"], "runtime")
                file_sha.assert_not_called()

    def test_fast_path_hashes_manifest_but_no_package_file(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, release, _package = self.publish_fixture(root)
            manifest = release / "remote-dev-runtime.json"
            expected_manifest_sha = self.m.file_sha(manifest)
            real_sha256 = self.m.hashlib.sha256
            hashed_payloads = []

            def observe(value=b""):
                hashed_payloads.append(value)
                return real_sha256(value)

            with mock.patch.object(
                self.m, "file_sha", side_effect=AssertionError("package hashed")
            ), mock.patch.object(
                self.m.hashlib, "sha256", side_effect=observe
            ), mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ):
                current = self.m.state()
                for command in (["status"], ["status", "--menu"], ["resolve"]):
                    with contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(self.m.main(command), 0)
            self.assertEqual(current["kind"], "runtime")
            observed = [real_sha256(value).hexdigest() for value in hashed_payloads]
            self.assertIn(expected_manifest_sha, observed)

    def test_same_size_tamper_and_restored_mtime_force_full_failure(self):
        for restore_mtime in (False, True):
            with self.subTest(
                restore_mtime=restore_mtime
            ), tempfile.TemporaryDirectory() as text:
                root = Path(text)
                _asset, _release, package = self.publish_fixture(root)
                binary = package / "bin/codex"
                before = binary.stat()
                original = binary.read_bytes()
                binary.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                binary.chmod(before.st_mode & 0o777)
                if restore_mtime:
                    os.utime(binary, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertEqual(binary.stat().st_mtime_ns, before.st_mtime_ns)
                with mock.patch.object(
                    self.m, "file_sha", wraps=self.m.file_sha
                ) as file_sha:
                    current = self.runtime_state()
                self.assertEqual(current["kind"], "damaged")
                self.assertGreater(file_sha.call_count, 0)

    def test_mode_changes_invalidate_trust_without_changing_acceptance_policy(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, _release, package = self.publish_fixture(root)
            metadata = package / "codex-package.json"
            original_mode = metadata.stat().st_mode & 0o777
            metadata.chmod(0o640)
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                self.assertEqual(self.runtime_state()["kind"], "runtime")
                self.assertGreater(file_sha.call_count, 0)
            metadata.chmod(original_mode)
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                self.assertEqual(self.runtime_state()["kind"], "runtime")
                self.assertGreater(file_sha.call_count, 0)

    @unittest.skipUnless(os.geteuid() == 0, "root is required to change ownership")
    def test_owner_change_is_rejected_by_current_contract(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, _release, package = self.publish_fixture(root)
            binary = package / "bin/codex"
            os.chown(binary, self.m.NOBODY, self.m.NOBODY)
            self.assertEqual(self.runtime_state()["kind"], "damaged")

    def test_file_set_and_symlink_changes_are_rejected(self):
        cases = ("added", "deleted", "file-symlink", "directory-symlink")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as text:
                root = Path(text)
                _asset, _release, package = self.publish_fixture(root)
                if case == "added":
                    (package / "extra").write_text("extra\n", encoding="utf-8")
                    (package / "extra").chmod(0o600)
                elif case == "deleted":
                    (package / "codex-resources/bwrap").unlink()
                elif case == "file-symlink":
                    path = package / "codex-resources/bwrap"
                    path.unlink()
                    path.symlink_to(package / "bin/codex")
                else:
                    directory = package / "codex-resources"
                    for child in directory.iterdir():
                        child.unlink()
                    directory.rmdir()
                    directory.symlink_to(package / "bin")
                self.assertEqual(self.runtime_state()["kind"], "damaged")

    def test_manifest_and_pointer_metadata_changes_force_full_verification(self):
        for changed in ("manifest", "current"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as text:
                root = Path(text)
                _asset, release, _package = self.publish_fixture(root)
                if changed == "manifest":
                    path = release / "remote-dev-runtime.json"
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["installed_at"] += 1
                    path.write_text(
                        json.dumps(data, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    path.chmod(0o600)
                else:
                    path = self.m.ROOT / "current"
                    previous_name = path.read_text(encoding="utf-8").strip()
                    next_asset = self.asset("0.149.0", "b" * 64)
                    with mock.patch.object(
                        self.m, "target", return_value=next_asset["target"]
                    ):
                        self.m.publish(
                            self.package(root, next_asset["version"]),
                            next_asset,
                            next_asset["url"],
                        )
                    path.write_text(previous_name + "\n", encoding="utf-8")
                    path.chmod(0o600)
                with mock.patch.object(
                    self.m, "file_sha", wraps=self.m.file_sha
                ) as file_sha:
                    self.assertEqual(self.runtime_state()["kind"], "runtime")
                    self.assertGreater(file_sha.call_count, 0)

    def test_stamp_invalid_states_always_force_full_and_repair(self):
        cases = (
            "missing",
            "corrupt",
            "truncated",
            "schema",
            "extra-key",
            "release",
            "symlink",
            "perms",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as text:
                root = Path(text)
                self.publish_fixture(root)
                stamp = self.m.stamp_path()
                if case == "missing":
                    stamp.unlink()
                elif case == "corrupt":
                    stamp.write_text("not-json\n", encoding="utf-8")
                elif case == "truncated":
                    stamp.write_text('{"schema_version":', encoding="utf-8")
                elif case == "schema":
                    data = json.loads(stamp.read_text(encoding="utf-8"))
                    data["schema_version"] = 999
                    stamp.write_text(json.dumps(data) + "\n", encoding="utf-8")
                elif case == "extra-key":
                    data = json.loads(stamp.read_text(encoding="utf-8"))
                    data["unexpected"] = True
                    stamp.write_text(json.dumps(data) + "\n", encoding="utf-8")
                elif case == "release":
                    data = json.loads(stamp.read_text(encoding="utf-8"))
                    data["release_name"] = data["release_name"][:-8] + "00000000"
                    stamp.write_text(json.dumps(data) + "\n", encoding="utf-8")
                elif case == "symlink":
                    stamp.unlink()
                    outside = root / "outside-stamp"
                    outside.write_text("keep\n", encoding="utf-8")
                    stamp.symlink_to(outside)
                else:
                    stamp.chmod(0o666)
                with mock.patch.object(
                    self.m, "file_sha", wraps=self.m.file_sha
                ) as file_sha:
                    self.assertEqual(self.runtime_state()["kind"], "runtime")
                    self.assertGreater(file_sha.call_count, 0)
                self.assertIsNotNone(self.m.read_verification_stamp())
                self.assertFalse(stamp.is_symlink())
                self.assertEqual(stamp.stat().st_mode & 0o022, 0)

    @unittest.skipUnless(os.geteuid() == 0, "root is required to change ownership")
    def test_wrong_stamp_owner_forces_full_and_atomic_repair(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            os.chown(self.m.stamp_path(), self.m.NOBODY, self.m.NOBODY)
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                self.assertEqual(self.runtime_state()["kind"], "runtime")
                self.assertGreater(file_sha.call_count, 0)
            self.assertEqual(self.m.stamp_path().stat().st_uid, os.geteuid())

    def test_legitimate_inode_change_and_empty_directory_refresh_stamp(self):
        for case in ("inode", "empty-directory"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as text:
                root = Path(text)
                _asset, _release, package = self.publish_fixture(root)
                if case == "inode":
                    path = package / "codex-package.json"
                    replacement = package / ".replacement"
                    replacement.write_bytes(path.read_bytes())
                    replacement.chmod(path.stat().st_mode & 0o777)
                    os.replace(replacement, path)
                else:
                    (package / "codex-resources/empty").mkdir(mode=0o700)
                with mock.patch.object(
                    self.m, "file_sha", wraps=self.m.file_sha
                ) as file_sha:
                    self.assertEqual(self.runtime_state()["kind"], "runtime")
                    self.assertGreater(file_sha.call_count, 0)
                self.assertIsNotNone(self.m.read_verification_stamp())

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

    def test_publish_oserror_is_manager_error_and_preserves_previous_runtime(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            package = self.package(root)
            self.m.ROOT = root / "runtime"
            asset = self.asset()
            with mock.patch.object(self.m, "target", return_value=asset["target"]):
                self.m.publish(package, asset, asset["url"])
                previous = (self.m.ROOT / "current").read_text()
                with mock.patch.object(
                    self.m.shutil, "copytree", side_effect=OSError("read-only")
                ), self.assertRaisesRegex(self.m.ManagerError, "cannot publish"):
                    self.m.publish(package, asset, asset["url"])
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
                releases = self.m.ROOT / "releases"
                stale = releases / ".candidate-abandoned"
                stale.mkdir()
                (stale / "partial").write_text("stale\n", encoding="utf-8")
                self.m.publish(
                    self.package(root, "0.149.0"), second_asset, second_asset["url"]
                )
            current_name = (self.m.ROOT / "current").read_text().strip()
            self.assertNotEqual(previous_name, current_name)
            self.assertTrue((releases / previous_name).is_dir())
            self.assertTrue((releases / current_name).is_dir())
            self.assertFalse(stale.exists())

    def test_stamp_failure_after_pointer_does_not_rollback_publication(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "runtime"
            first = self.asset("0.148.0", "a" * 64)
            second = self.asset("0.149.0", "b" * 64)
            with mock.patch.object(self.m, "target", return_value=first["target"]):
                self.m.publish(
                    self.package(root, first["version"]), first, first["url"]
                )
                previous = (self.m.ROOT / "current").read_text(encoding="utf-8")
                stderr = io.StringIO()
                with mock.patch.object(
                    self.m,
                    "write_verification_stamp",
                    side_effect=self.m.ManagerError("synthetic stamp failure"),
                ), contextlib.redirect_stderr(stderr):
                    self.m.publish(
                        self.package(root, second["version"]), second, second["url"]
                    )
            current = (self.m.ROOT / "current").read_text(encoding="utf-8")
            self.assertNotEqual(current, previous)
            self.assertTrue(current.startswith("0.149.0-"))
            self.assertIn("stamp could not be initialized", stderr.getvalue())
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha:
                self.assertEqual(self.runtime_state()["kind"], "runtime")
                self.assertGreater(file_sha.call_count, 0)

    def test_update_staging_is_fixed_ignores_tmpdir_and_cleans(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            fixed = self.staging_root(root)
            caller_tmp = root / "caller-controlled-tmp"
            caller_tmp.mkdir()
            self.assertEqual(
                self.m.STAGING_ROOT, Path("/run/remote-dev-codex-update")
            )
            self.assertFalse(self.m.STAGING_ROOT.is_relative_to(Path("/tmp")))
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m, "probe_staging_execution"
            ), mock.patch.dict(os.environ, {"TMPDIR": str(caller_tmp)}):
                with self.m.update_staging() as staging:
                    created = staging
                    self.assertEqual(staging.parent, fixed)
                    self.assertFalse(staging.is_relative_to(caller_tmp))
                    self.assertEqual(staging.stat().st_mode & 0o777, 0o711)
                self.assertFalse(created.exists())
                self.assertEqual(list(fixed.iterdir()), [])

    def test_update_staging_cleans_after_error_and_signal(self):
        with tempfile.TemporaryDirectory() as text:
            fixed = self.staging_root(Path(text))
            previous_handlers = {
                signum: signal.getsignal(signum)
                for signum in (
                    getattr(signal, "SIGHUP", None),
                    getattr(signal, "SIGTERM", None),
                )
                if signum is not None
            }
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m, "probe_staging_execution"
            ):
                with self.assertRaisesRegex(self.m.ManagerError, "synthetic failure"):
                    with self.m.update_staging() as staging:
                        failed = staging
                        raise self.m.ManagerError("synthetic failure")
                self.assertFalse(failed.exists())

                if hasattr(signal, "SIGTERM"):
                    with self.assertRaises(self.m.OperationInterrupted):
                        with self.m.update_staging() as staging:
                            interrupted = staging
                            signal.raise_signal(signal.SIGTERM)
                    self.assertFalse(interrupted.exists())
                self.assertEqual(list(fixed.iterdir()), [])
            for signum, handler in previous_handlers.items():
                self.assertEqual(signal.getsignal(signum), handler)

    def test_staging_execution_probe_fails_before_download(self):
        with tempfile.TemporaryDirectory() as text:
            fixed = self.staging_root(Path(text))
            download = mock.Mock()
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m.subprocess,
                "run",
                side_effect=PermissionError("synthetic noexec"),
            ), mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ), mock.patch.object(
                self.m, "state", return_value={"kind": "bundled"}
            ), mock.patch.object(
                self.m, "latest_asset", return_value=self.asset("0.149.0")
            ), mock.patch.object(
                self.m, "download", download
            ), self.assertRaisesRegex(
                self.m.ManagerError, "does not permit candidate execution"
            ):
                self.m.update_runtime(yes=True)
            download.assert_not_called()
            self.assertEqual(list(fixed.iterdir()), [])

    def test_candidate_rejects_a_nontraversable_parent(self):
        with tempfile.TemporaryDirectory() as text:
            fixed = self.staging_root(Path(text))
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m, "probe_staging_execution"
            ):
                with self.m.update_staging() as staging:
                    package_bin = staging / "package" / "bin"
                    package_bin.mkdir(parents=True)
                    (staging / "package").chmod(0o755)
                    candidate = package_bin / "codex"
                    candidate.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    candidate.chmod(0o755)
                    package_bin.chmod(0o600)
                    try:
                        expected = (
                            "candidate path parent is not traversable by the probe "
                            f"identity: {package_bin}"
                        )
                        with self.assertRaisesRegex(
                            self.m.ManagerError, rf"^{re.escape(expected)}$"
                        ):
                            self.m.require_candidate_path(candidate, executable=True)
                    finally:
                        package_bin.chmod(0o755)

    @unittest.skipUnless(os.geteuid() == 0, "root is required to verify identity")
    def test_all_candidate_processes_share_the_nobody_identity_contract(self):
        with tempfile.TemporaryDirectory() as text:
            fixed = self.staging_root(Path(text))
            fixed.mkdir(mode=0o711)
            fixed.chmod(0o711)
            completed = self.m.subprocess.CompletedProcess([], 0)
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m, "require_candidate_path"
            ), mock.patch.object(
                self.m.subprocess, "run", return_value=completed
            ) as run, mock.patch.object(
                self.m.subprocess, "Popen", side_effect=OSError("stop after launch")
            ) as popen:
                self.m.probe_staging_execution()
                with self.assertRaisesRegex(self.m.ManagerError, "Codex probe"):
                    self.m.candidate_run(
                        ["/candidate/bin/codex"],
                        Path("/candidate/cwd"),
                        Path("/candidate/home"),
                    )
                with self.assertRaisesRegex(self.m.ManagerError, "code-mode host"):
                    self.m.probe_host(
                        Path("/candidate/bin/codex-code-mode-host"),
                        Path("/candidate/cwd"),
                        Path("/candidate/home"),
                    )

            calls = [run.call_args, *popen.call_args_list]
            self.assertEqual(len(calls), 3)
            expected = {"user": 65534, "group": 65534, "extra_groups": []}
            for call in calls:
                self.assertEqual(
                    {name: call.kwargs[name] for name in expected}, expected
                )
                self.assertNotIn("preexec_fn", call.kwargs)

    def test_candidate_identity_contract_does_not_force_nonroot(self):
        with mock.patch.object(self.m.os, "geteuid", return_value=1234):
            self.assertEqual(self.m.candidate_identity_kwargs(), {})

    @unittest.skipUnless(os.geteuid() == 0, "root is required to verify privilege drop")
    def test_candidate_uses_nobody_and_synthetic_state(self):
        with tempfile.TemporaryDirectory(
            prefix="remote-dev-codex-candidate-test-", dir="/run"
        ) as text:
            root = Path(text)
            fixed = self.staging_root(root)
            real_home = root / "real-codex-home"
            real_home.mkdir(mode=0o700)
            credential = real_home / "auth.json"
            credential.write_text("synthetic-real-credential\n", encoding="utf-8")
            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.dict(
                os.environ,
                {
                    "HOME": "/root",
                    "CODEX_HOME": str(real_home),
                    "OPENAI_API_KEY": "synthetic-secret",
                    "GH_TOKEN": "synthetic-gh-secret",
                },
            ):
                with self.m.update_staging() as staging:
                    package_bin = staging / "package" / "bin"
                    package_bin.mkdir(parents=True)
                    (staging / "package").chmod(0o755)
                    package_bin.chmod(0o755)
                    candidate = package_bin / "codex"
                    candidate.write_text(
                        "#!/bin/sh\n"
                        "set -eu\n"
                        "printf 'uid=%s\\n' \"$(id -u)\"\n"
                        "printf 'gid=%s\\n' \"$(id -g)\"\n"
                        "printf 'groups=%s\\n' \"$(sed -n "
                        "'s/^Groups:[[:space:]]*//p' /proc/self/status)\"\n"
                        "printf 'home=%s\\n' \"$HOME\"\n"
                        "printf 'codex_home=%s\\n' \"$CODEX_HOME\"\n"
                        "printf 'cwd=%s\\n' \"$(pwd -P)\"\n"
                        "printf 'openai=%s\\n' \"${OPENAI_API_KEY-unset}\"\n"
                        "printf 'gh=%s\\n' \"${GH_TOKEN-unset}\"\n"
                        "touch \"$HOME/probe-created\"\n",
                        encoding="utf-8",
                    )
                    candidate.chmod(0o755)
                    home, cwd = self.m.prepare_candidate_directories(staging)
                    self.assertEqual(
                        self.m.STAGING_ROOT.stat().st_mode & 0o777, 0o711
                    )
                    self.assertEqual(staging.stat().st_mode & 0o777, 0o711)
                    for private in (home, cwd):
                        info = private.stat()
                        self.assertEqual((info.st_uid, info.st_gid), (65534, 65534))
                        self.assertEqual(info.st_mode & 0o777, 0o700)
                    result = self.m.candidate_run([str(candidate)], cwd, home)
                    lines = dict(line.split("=", 1) for line in result.stdout.splitlines())
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(lines["uid"], str(self.m.NOBODY))
                    self.assertEqual(lines["gid"], str(self.m.NOBODY))
                    self.assertEqual(lines["groups"], "")
                    self.assertEqual(lines["home"], str(home))
                    self.assertEqual(lines["codex_home"], str(home / ".codex"))
                    self.assertEqual(lines["cwd"], str(cwd))
                    self.assertEqual(lines["openai"], "unset")
                    self.assertEqual(lines["gh"], "unset")
                    self.assertTrue((home / "probe-created").is_file())
                    self.assertEqual(credential.read_text(), "synthetic-real-credential\n")
                    created = staging
                self.assertFalse(created.exists())

    def test_failed_update_cleans_staging_and_preserves_previous_generation(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            root.chmod(0o711)
            fixed = self.staging_root(root)
            self.m.ROOT = root / "runtime"
            previous_asset = self.asset("0.148.0", "a" * 64)
            next_asset = self.asset("0.149.0", "b" * 64)
            with mock.patch.object(
                self.m, "target", return_value=previous_asset["target"]
            ):
                self.m.publish(
                    self.package(root, previous_asset["version"]),
                    previous_asset,
                    previous_asset["url"],
                )
            previous = (self.m.ROOT / "current").read_text(encoding="utf-8")

            def extract_fixture(_archive, package):
                package.mkdir()

            with mock.patch.object(self.m, "STAGING_ROOT", fixed), mock.patch.object(
                self.m, "probe_staging_execution"
            ), mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ), mock.patch.object(
                self.m,
                "state",
                return_value={"kind": "runtime", "runtime": "0.148.0"},
            ), mock.patch.object(
                self.m, "latest_asset", return_value=next_asset
            ), mock.patch.object(
                self.m, "download", return_value=next_asset["url"]
            ), mock.patch.object(
                self.m, "extract", side_effect=extract_fixture
            ), mock.patch.object(
                self.m, "package_metadata"
            ), mock.patch.object(
                self.m,
                "validate_candidate",
                side_effect=self.m.ManagerError("candidate command timed out"),
            ):
                with self.assertRaisesRegex(self.m.ManagerError, "timed out"):
                    self.m.update_runtime(yes=True)

            self.assertEqual(
                (self.m.ROOT / "current").read_text(encoding="utf-8"), previous
            )
            self.assertEqual(list(fixed.iterdir()), [])

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

    def test_verify_always_full_hashes_and_refreshes_stamp(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            before = json.loads(self.m.stamp_path().read_text(encoding="utf-8"))
            with mock.patch.object(
                self.m, "file_sha", wraps=self.m.file_sha
            ) as file_sha, mock.patch.object(
                self.m.time, "time", return_value=before["verified_at"] + 10
            ):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(self.m.main(["verify"]), 0)
                self.assertGreater(file_sha.call_count, 0)
            self.assertIn("full integrity: OK (runtime 0.148.0)", stdout.getvalue())
            after = json.loads(self.m.stamp_path().read_text(encoding="utf-8"))
            self.assertEqual(after["verified_at"], before["verified_at"] + 10)

    def test_verify_corruption_fails_and_does_not_publish_new_trust(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, _release, package = self.publish_fixture(root)
            stamp_before = self.m.stamp_path().read_bytes()
            path = package / "bin/codex"
            content = path.read_bytes()
            path.write_bytes(bytes([content[0] ^ 1]) + content[1:])
            path.chmod(0o700)
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(self.m.main(["verify"]), 1)
            self.assertIn("full integrity: FAILED", stderr.getvalue())
            self.assertEqual(self.m.stamp_path().read_bytes(), stamp_before)

    def test_verify_without_optional_runtime_is_bundled_only_and_offline(self):
        with tempfile.TemporaryDirectory() as text:
            self.m.ROOT = Path(text) / "missing-runtime"
            stdout = io.StringIO()
            with mock.patch.object(
                self.m, "opener", side_effect=AssertionError("network used")
            ), contextlib.redirect_stdout(stdout):
                self.assertEqual(self.m.main(["verify"]), 0)
            self.assertIn(
                "bundled-only; optional runtime not installed", stdout.getvalue()
            )

    def test_resolve_uses_fully_verified_runtime_when_stamp_write_fails(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, _release, package = self.publish_fixture(root)
            self.m.stamp_path().unlink()
            runtime_binary = package / "bin/codex"
            file_sha_calls = 0
            original_file_sha = self.m.file_sha

            def counted_file_sha(path):
                nonlocal file_sha_calls
                file_sha_calls += 1
                return original_file_sha(path)

            with mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ), mock.patch.object(
                self.m, "file_sha", side_effect=counted_file_sha
            ), mock.patch.object(
                self.m,
                "write_verification_stamp",
                side_effect=self.m.ManagerError("synthetic read-only state"),
            ):
                for invocation in range(2):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with contextlib.redirect_stdout(
                        stdout
                    ), contextlib.redirect_stderr(stderr):
                        self.assertEqual(self.m.main(["resolve"]), 0)
                    self.assertEqual(stdout.getvalue().strip(), str(runtime_binary))
                    self.assertIn(
                        "passed full integrity verification", stderr.getvalue()
                    )
                    self.assertGreater(file_sha_calls, invocation * 5)
            self.assertFalse(self.m.stamp_path().exists())

    def test_verify_fails_operationally_when_stamp_write_fails(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            with mock.patch.object(
                self.m,
                "write_verification_stamp",
                side_effect=self.m.ManagerError("synthetic read-only state"),
            ):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    self.assertEqual(self.m.main(["verify"]), 1)
            self.assertIn("full integrity: FAILED", stderr.getvalue())
            self.assertIn("synthetic read-only state", stderr.getvalue())

    def test_stamp_refresh_rechecks_current_and_never_publishes_stale_state(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            inspection = self.m.inspect_active_runtime(full_hash=True)
            self.assertIsNotNone(inspection)
            self.m.stamp_path().unlink()
            current = self.m.ROOT / "current"
            value = current.read_text(encoding="utf-8")
            current.write_text(value, encoding="utf-8")
            current.chmod(0o600)
            refreshed = self.m.refresh_verification_stamp(inspection)
            self.assertFalse(refreshed.refreshed)
            self.assertTrue(refreshed.stale)
            self.assertFalse(self.m.stamp_path().exists())

    def test_publication_stamp_matches_only_the_final_active_generation(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            _asset, release, _package = self.publish_fixture(root)
            stamp = self.m.read_verification_stamp()
            self.assertIsNotNone(stamp)
            stamp_info = self.m.stamp_path().lstat()
            self.assertTrue(self.m.stat.S_ISREG(stamp_info.st_mode))
            self.assertEqual(stamp_info.st_uid, os.geteuid())
            self.assertEqual(stamp_info.st_mode & 0o777, 0o600)
            self.assertEqual(
                set(stamp),
                {
                    "schema_version",
                    "fingerprint_algorithm",
                    "release_name",
                    "runtime_version",
                    "target",
                    "manifest_sha256",
                    "fingerprints",
                    "verified_at",
                },
            )
            self.assertEqual(stamp["schema_version"], self.m.STAMP_SCHEMA)
            self.assertEqual(
                stamp["fingerprint_algorithm"], self.m.FINGERPRINT_ALGORITHM
            )
            self.assertEqual(stamp["release_name"], release.name)
            self.assertEqual(
                stamp["manifest_sha256"],
                self.m.file_sha(release / "remote-dev-runtime.json"),
            )
            self.assertEqual(
                stamp["release_name"],
                (self.m.ROOT / "current").read_text(encoding="utf-8").strip(),
            )

    def test_verify_never_opens_network_with_installed_runtime(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.publish_fixture(root)
            with mock.patch.object(
                self.m, "opener", side_effect=AssertionError("network used")
            ):
                self.assertEqual(self.m.main(["verify"]), 0)

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

    def test_remove_recovers_damaged_pointer_without_following_symlink(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "runtime"
            self.m.ROOT.mkdir()
            outside = root / "outside"
            outside.write_text("keep\n", encoding="utf-8")
            (self.m.ROOT / "current").symlink_to(outside)
            releases = self.m.ROOT / "releases"
            (releases / "stale").mkdir(parents=True)

            self.m.remove_runtime(yes=True)

            self.assertEqual(outside.read_text(encoding="utf-8"), "keep\n")
            self.assertFalse((self.m.ROOT / "current").exists())
            self.assertFalse((self.m.ROOT / "current").is_symlink())
            self.assertEqual(list(releases.iterdir()), [])

    def test_status_and_resolve_never_open_network(self):
        with tempfile.TemporaryDirectory() as text:
            root = Path(text)
            self.m.ROOT = root / "missing-runtime"
            with mock.patch.object(
                self.m, "bundled_version", return_value="0.147.0"
            ), mock.patch.object(
                self.m, "opener", side_effect=AssertionError("network used")
            ):
                for command in (["status"], ["resolve"]):
                    with self.subTest(command=command[0], installed=False):
                        stdout = io.StringIO()
                        with contextlib.redirect_stdout(stdout):
                            self.assertEqual(self.m.main(command), 0)
                        self.assertTrue(stdout.getvalue().strip())

            asset = self.asset()
            self.m.ROOT = root / "runtime"
            with mock.patch.object(self.m, "target", return_value=asset["target"]):
                self.m.publish(self.package(root), asset, asset["url"])
                with mock.patch.object(
                    self.m, "bundled_version", return_value="0.147.0"
                ), mock.patch.object(
                    self.m, "opener", side_effect=AssertionError("network used")
                ):
                    for command in (["status"], ["resolve"]):
                        with self.subTest(command=command[0], installed=True):
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

    @unittest.skipUnless(
        os.geteuid() == 0, "root is required for executable /run fixture"
    )
    def test_doctor_runs_full_verify_before_status_and_propagates_failure(self):
        with tempfile.TemporaryDirectory(prefix="doctor-test-", dir="/run") as text:
            root = Path(text)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            runtime_lib = root / "remote-dev-runtime.sh"
            runtime_lib.write_text(
                "remote_dev_resolve_role() { printf '%s\\n' codex; }\n",
                encoding="utf-8",
            )
            log = root / "runtime.log"
            manager = bin_dir / "remote-dev-codex-runtime"
            manager.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"$1\" >>\"$DOCTOR_RUNTIME_LOG\"\n"
                "if [ \"$1\" = verify ]; then\n"
                "  if [ \"${DOCTOR_VERIFY_FAIL:-0}\" = 1 ]; then\n"
                "    echo 'ERROR: Codex runtime full integrity: FAILED: "
                "synthetic' >&2\n"
                "    exit 1\n"
                "  fi\n"
                "  echo 'Codex runtime full integrity: OK (runtime 0.149.0)'\n"
                "else\n"
                "  echo 'Codex bundled: 0.148.0'\n"
                "  echo 'Codex runtime: 0.149.0'\n"
                "  echo 'Codex active source: runtime'\n"
                "fi\n",
                encoding="utf-8",
            )
            manager.chmod(0o755)
            context7 = bin_dir / "remote-dev-context7"
            generic = "#!/bin/sh\nexit 0\n"
            context7.write_text(generic, encoding="utf-8")
            context7.chmod(0o755)
            commands = (
                "start-remote-dev-web",
                "attach-remote-dev-tmux",
                "remote-dev-menu",
                "remote-dev-healthcheck",
                "remote-dev-doctor",
                "remote-dev-version",
                "gh",
                "git",
                "python",
                "node",
                "npm",
                "uv",
                "mise",
                "ttyd",
                "tmux",
                "ssh",
                "rg",
                "fd",
                "codex",
                "run-codex",
            )
            for name in commands:
                path = bin_dir / name
                path.write_text(generic, encoding="utf-8")
                path.chmod(0o755)
            doctor = root / "remote-dev-doctor.sh"
            source = DOCTOR.read_text(encoding="utf-8")
            source = source.replace(
                "runtime_lib=/usr/local/lib/remote-dev/remote-dev-runtime.sh",
                f"runtime_lib={runtime_lib}",
            ).replace(
                "/usr/local/bin/remote-dev-codex-runtime", str(manager)
            ).replace(
                "/usr/local/bin/remote-dev-context7", str(context7)
            )
            doctor.write_text(source, encoding="utf-8")
            doctor.chmod(0o755)
            workspace = root / "workspace"
            gh_home = root / "gh"
            codex_home = root / "codex"
            runtime_root = root / "runtime"
            for path in (workspace, gh_home, codex_home, runtime_root):
                path.mkdir()
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "HOME": str(root),
                "WORKSPACE": str(workspace),
                "GH_CONFIG_DIR": str(gh_home),
                "CODEX_HOME": str(codex_home),
                "REMOTE_DEV_CODEX_RUNTIME_ROOT": str(runtime_root),
                "DOCTOR_RUNTIME_LOG": str(log),
            }
            success = subprocess.run(
                ["/bin/bash", str(doctor)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
            self.assertIn("Codex runtime full integrity: OK", success.stdout)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(), ["verify", "status"]
            )

            log.unlink()
            env["DOCTOR_VERIFY_FAIL"] = "1"
            failure = subprocess.run(
                ["/bin/bash", str(doctor)],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("full integrity: unavailable", failure.stdout)
            self.assertEqual(
                log.read_text(encoding="utf-8").splitlines(), ["verify", "status"]
            )


if __name__ == "__main__":
    unittest.main()
