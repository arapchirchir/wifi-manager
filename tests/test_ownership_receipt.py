"""Offline tests of receipt file safety in temporary private directories."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from installer.ownership_receipt import read_receipt, write_new_receipt


def inventory():
    return {
        "version": 1,
        "interfaces": [{"name": "ap0", "kind": "ap", "ifindex": 103}],
    }


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.path = self.private / "created.json"

    def test_write_and_read(self):
        receipt = inventory()
        write_new_receipt(self.path, receipt)
        self.assertEqual(read_receipt(self.path), receipt)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_exclusive_no_overwrite(self):
        write_new_receipt(self.path, inventory())
        original = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            write_new_receipt(self.path, inventory())
        self.assertEqual(self.path.read_bytes(), original)

    def test_rejects_existing_symlink(self):
        target = self.private / "victim"
        target.write_text("unchanged")
        self.path.symlink_to(target)
        with self.assertRaises(FileExistsError):
            write_new_receipt(self.path, inventory())
        self.assertEqual(target.read_text(), "unchanged")
        with self.assertRaises(OSError):
            read_receipt(self.path)

    def test_rejects_public_directory(self):
        self.private.chmod(0o755)
        with self.assertRaises(ValueError):
            write_new_receipt(self.path, inventory())

    def test_rejects_public_receipt(self):
        write_new_receipt(self.path, inventory())
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            read_receipt(self.path)

    def test_rejects_forged_invalid_data(self):
        self.path.write_text(json.dumps({
            "version": 1,
            "interfaces": [{"name": "ap0", "kind": "ap", "ifindex": -1}],
        }))
        self.path.chmod(0o600)
        with self.assertRaises(ValueError):
            read_receipt(self.path)

    def test_rejects_invalid_inventory_before_write(self):
        with self.assertRaises(ValueError):
            write_new_receipt(self.path, {})
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
