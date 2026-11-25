#!/usr/bin/env python3
"""Synthetic mountinfo regression tests; no real filesystem or SMB claims."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import data_layout
from lib.exchange_mount import check_host, check_runtime, parse_mountinfo

ROOT = "1 0 0:1 / / rw - overlay overlay rw"
PARENT = "2 1 0:2 / /data rw - zfs pool/root rw"
EXCHANGE = "3 2 0:3 / /data/exchange rw - zfs pool/root/exchange rw"
RUNTIME = "3 1 0:3 / /exchange rw - zfs pool/root/exchange rw"
IDENTITY = "zfs:pool/root/exchange"


def mounts(*lines):
    return parse_mountinfo("\n".join(lines))


class ExchangeTests(unittest.TestCase):
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
                (ROOT, parent, exchange.replace("pool/root/exchange", "pool/other")),
                (ROOT, parent, exchange.replace("0:3", "0:2")),
                (ROOT, parent, exchange, exchange.replace(tmp + "/exchange", tmp + "/state/alias")),
                (ROOT, parent, exchange, exchange.replace(tmp + "/exchange", tmp + "/exchange/nested")),
            ):
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    check_host(root, mounts(*rows))

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

    def test_mountinfo_space_escaping_and_invalid(self):
        m = mounts(ROOT, r"2 1 8:1 / /data\040root rw - ext4 /dev/loop1 rw")
        self.assertEqual(m[1].target, "/data root")
        for text in ("", "garbage", "1 0 unknown / / rw - zfs pool/root rw"):
            with self.assertRaises(ValueError):
                parse_mountinfo(text)


if __name__ == "__main__":
    unittest.main()
