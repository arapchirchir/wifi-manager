"""Configuration-only rollback tests using disposable files."""
from pathlib import Path
import tempfile
import unittest

from installer.hostapd_transaction import (
    apply_channel, rollback_channel, render_channel, ConfigError
)


ORIGINAL = b"interface=ap0\nssid=Techworld-WiFi\nhw_mode=g\nchannel=6\n"


class HostapdTransactionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.file = Path(temp.name) / "hostapd.conf"
        self.file.write_bytes(ORIGINAL)

    def test_channel_change_and_restore(self):
        transaction = apply_channel(self.file, 11)
        self.assertIn(b"channel=11", self.file.read_bytes())
        self.assertTrue(rollback_channel(self.file, transaction))
        self.assertEqual(self.file.read_bytes(), ORIGINAL)

    def test_matching_channel_does_not_change(self):
        transaction = apply_channel(self.file, 6)
        self.assertFalse(transaction["modified"])
        self.assertFalse(rollback_channel(self.file, transaction))

    def test_external_modification_blocks_rollback(self):
        transaction = apply_channel(self.file, 11)
        self.file.write_bytes(b"modified by someone else\n")
        with self.assertRaises(ConfigError):
            rollback_channel(self.file, transaction)
        self.assertEqual(self.file.read_bytes(), b"modified by someone else\n")

    def test_invalid_channel_rejected(self):
        with self.assertRaises(ConfigError):
            apply_channel(self.file, 36)
        self.assertEqual(self.file.read_bytes(), ORIGINAL)

    def test_unknown_interface_config_refused(self):
        self.file.write_bytes(ORIGINAL.replace(b"interface=ap0", b"interface=wlp109s0"))
        with self.assertRaises(ConfigError):
            apply_channel(self.file, 11)

    def test_symlink_rejected(self):
        target = self.file
        alias = target.parent / "alias.conf"
        alias.symlink_to(target)
        with self.assertRaises(ConfigError):
            apply_channel(alias, 11)
        self.assertEqual(target.read_bytes(), ORIGINAL)

    def test_duplicate_channel_rejected(self):
        with self.assertRaises(ConfigError):
            render_channel(ORIGINAL + b"channel=11\n", 11)


if __name__ == "__main__":
    unittest.main()
