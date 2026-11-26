#!/usr/bin/env python3
"""Synthetic mountinfo regression tests; no real filesystem or SMB claims."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from exchange_fixture import adapt_exchange_off, EXCHANGE_COMMAND
from lib import data_layout
from lib.exchange_mount import check_host, check_runtime, main, parse_mountinfo

ROOT = "1 0 0:1 / / rw - overlay overlay rw"
PARENT = "2 1 0:2 / /data rw - zfs pool/root rw"
EXCHANGE = "3 2 0:3 / /data/exchange rw - zfs pool/root/exchange rw"
RUNTIME = "3 1 0:3 / /exchange rw - zfs pool/root/exchange rw"
IDENTITY = "zfs:pool/root/exchange"


def mounts(*lines):
    return parse_mountinfo("\n".join(lines))


class ExchangeTests(unittest.TestCase):
    def test_absent_target_skips_mount_table_only_when_disabled(self):
        with patch.dict("os.environ", REMOTE_DEV_EXCHANGE_FS=""), \
             patch("os.lstat", side_effect=FileNotFoundError), \
             patch("lib.exchange_mount.read_mounts", side_effect=AssertionError):
            self.assertEqual(main(), 0)
        with patch.dict("os.environ", REMOTE_DEV_EXCHANGE_FS=IDENTITY), \
             patch("lib.exchange_mount.read_mounts", return_value=mounts(ROOT)):
            self.assertEqual(main(), 1)

    def test_host_fixture_isolates_inherited_identity_and_quotes_paths(self):
        with tempfile.TemporaryDirectory(prefix="exchange fixture ") as tmp:
            root = Path(tmp)
            source = Path(__file__).resolve().parent / "lib/exchange_mount.py"
            adapted = adapt_exchange_off(EXCHANGE_COMMAND, source, root)
            env = dict(os.environ, REMOTE_DEV_EXCHANGE_FS="zfs:inherited")
            result = subprocess.run(["bash", "-c", adapted], env=env,
                                    capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Exchange: OFF", result.stdout)
            checker, = root.glob("exchange-fixture-*/exchange_mount.py")
            blocked = subprocess.run([sys.executable, "-I", str(checker)], env=env,
                                     capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(blocked.returncode, 1, blocked.stderr)
            self.assertIn("Exchange: BLOCKED", blocked.stderr)
            self.assertFalse((checker.parent / "absent-exchange").exists())

    def test_runtime_off_and_on(self):
        self.assertFalse(check_runtime(mounts(ROOT), ""))
        self.assertTrue(check_runtime(mounts(ROOT, RUNTIME), IDENTITY))

    def test_runtime_rejects_mismatches_and_aliases(self):
        cases = [
            (mounts(ROOT), IDENTITY),
            (mounts(ROOT, RUNTIME), ""),
            (mounts(ROOT, RUNTIME), "zfs:wrong"),
            (mounts(ROOT, RUNTIME.replace(" / /exchange", " /private /exchange")), IDENTITY),
            (mounts(ROOT, RUNTIME.replace("0:3", "0:1")), IDENTITY),
            (mounts(ROOT, RUNTIME.replace("rw -", "ro -")), IDENTITY),
            (mounts(ROOT, RUNTIME.replace("rw -", "rw shared:1 -")), IDENTITY),
            (mounts(ROOT, RUNTIME, RUNTIME.replace("/exchange", "/exchange/nested", 1)), IDENTITY),
            (mounts(ROOT, RUNTIME, RUNTIME.replace("/exchange rw", "/workspace rw", 1)), IDENTITY),
            (mounts(ROOT, RUNTIME, RUNTIME), IDENTITY),
        ]
        for table, identity in cases:
            with self.subTest(table=table, identity=identity):
                with self.assertRaises(ValueError):
                    check_runtime(table, identity)

    def test_host_mount_required_and_direct_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exchange").mkdir()
            parent = PARENT.replace("/data", tmp)
            exchange = EXCHANGE.replace("/data/exchange", tmp + "/exchange")
            self.assertEqual(check_host(root, mounts(ROOT, parent, exchange)).identity, IDENTITY)
            for rows in (
                (ROOT, parent),
                (ROOT, parent, exchange, exchange.replace(tmp + "/exchange", "/unrelated/alias")),
                (ROOT, parent, exchange.replace("pool/root/exchange", "pool/other")),
                (ROOT, parent, exchange.replace("0:3", "0:2")),
                (ROOT, parent, exchange, exchange.replace(tmp + "/exchange", tmp + "/state/alias")),
                (ROOT, parent, exchange, exchange.replace(tmp + "/exchange", tmp + "/exchange/nested")),
            ):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    check_host(root, mounts(*rows))

    def test_zfs_properties_match_visible_parent_and_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "exchange").mkdir()
            table = mounts(ROOT, PARENT.replace("/data", tmp),
                           EXCHANGE.replace("/data/exchange", tmp + "/exchange"))
            listing = f"pool/root\tyes\t{tmp}\npool/root/exchange\tyes\t{tmp}/exchange\n"
            with patch("lib.exchange_mount.read_mounts", return_value=table), \
                 patch("lib.exchange_mount.verify_visible_device"), \
                 patch("lib.data_layout.subprocess.run") as run:
                for invalid in (listing.replace("yes", "no"), listing.replace(tmp, "/elsewhere")):
                    run.return_value = Mock(stdout=invalid)
                    with self.assertRaisesRegex(ValueError, "mounted properties"):
                        data_layout.validate_exchange(root)
                run.return_value = Mock(stdout=listing)
                self.assertEqual(data_layout.validate_exchange(root).identity, IDENTITY)

    def test_ordinary_directory_not_created_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_layout.initialize_layout(root, include_antigravity=True)
            self.assertFalse((root / "exchange").exists())
            with self.assertRaises(ValueError):
                data_layout.validate_exchange(root)
            (root / "exchange").symlink_to(root / "state")
            with patch("lib.exchange_mount.read_mounts", side_effect=AssertionError("must not inspect symlink")):
                with self.assertRaises(ValueError):
                    data_layout.validate_exchange(root)

    def test_unrelated_namespace_mount_does_not_block_startup(self):
        namespace = "4 1 0:4 net:[4026531840] /run/docker/netns/test rw - nsfs nsfs rw"
        self.assertFalse(check_runtime(mounts(ROOT, namespace), ""))
        self.assertTrue(check_runtime(mounts(ROOT, namespace, RUNTIME), IDENTITY))
        with self.assertRaises(ValueError):
            check_runtime(mounts(ROOT, namespace.replace("/run/docker/netns/test", "/exchange")),
                          "nsfs:nsfs")
        with self.assertRaises(ValueError):
            check_runtime(mounts(ROOT, RUNTIME.replace(" / /exchange", " net:[42] /exchange")),
                          IDENTITY)

    def test_unicode_whitespace_is_part_of_filename(self):
        m = mounts(ROOT, "2 1 8:1 / /data\u00a0root rw - ext4 /dev/loop1 rw")
        self.assertEqual(m[1].target, "/data\u00a0root")

    def test_mountinfo_space_escaping_and_invalid(self):
        m = mounts(ROOT, r"2 1 8:1 / /data\040root rw - ext4 /dev/loop1 rw")
        self.assertEqual(m[1].target, "/data root")
        for text in ("", "garbage", "1 0 unknown / / rw - zfs pool/root rw",
                     "2 1 0:4 / relative rw - nsfs nsfs rw"):
            with self.assertRaises(ValueError):
                parse_mountinfo(text)


if __name__ == "__main__":
    unittest.main()
