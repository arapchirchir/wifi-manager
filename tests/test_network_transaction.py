"""Offline integrated AP/config rollback tests; no host networking touched."""
import json
from pathlib import Path
import tempfile
import unittest

from installer.network_transaction import prepare_network, SetupError
from installer.ap_transaction import rollback


CONFIG = b"interface=ap0\nssid=Techworld-WiFi\nhw_mode=g\nchannel=6\n"


class FakeAdapter:
    def __init__(self, fail=None):
        self.links = {}
        self.next_index = 100
        self.fail = fail

    def inspect(self, name):
        return self.links.get(name)

    def create(self, name, kind):
        if self.fail == name:
            raise RuntimeError("simulated failure")
        self.next_index += 1
        self.links[name] = {"ifindex": self.next_index,
                            "kind": "AP" if kind == "ap" else "bridge"}

    def read(self, cmd):
        if cmd == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps([
                {"ifname": name, "ifindex": data["ifindex"],
                 "linkinfo": {"info_kind": "bridge"} if data["kind"] == "bridge" else {}}
                for name, data in self.links.items()
            ])
        if cmd == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n\ttype AP\n"
        raise AssertionError(cmd)

    def remove(self, name, kind, index):
        assert self.links[name]["ifindex"] == index
        self.links.pop(name)


class TransactionIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.receipts = root / "receipts"
        self.receipts.mkdir(mode=0o700)
        self.config = root / "hostapd.conf"
        self.config.write_bytes(CONFIG)

    def setup_network(self, adapter, check=lambda: ("Talai_B", 11, "10.12.133.234")):
        return prepare_network(
            adapter, receipt_dir=self.receipts, hostapd_path=self.config,
            channel=11, upstream_check=check,
        )

    def test_success_produces_receipts_and_config(self):
        adapter = FakeAdapter()
        report = self.setup_network(adapter)
        self.assertTrue(report["config_modified"])
        self.assertIn(b"channel=11", self.config.read_bytes())
        self.assertEqual(set(adapter.links), {"ap0", "br-techworld"})
        self.assertTrue((self.receipts / "ap0.json").exists())
        self.assertEqual(rollback(adapter, self.receipts), [])

    def test_ap_creation_failure_restores_config_and_bridge(self):
        adapter = FakeAdapter(fail="ap0")
        with self.assertRaisesRegex(SetupError, "rollback completed"):
            self.setup_network(adapter)
        self.assertEqual(self.config.read_bytes(), CONFIG)
        self.assertEqual(adapter.links, {})

    def test_upstream_change_rolls_back_everything(self):
        adapter = FakeAdapter()
        sequence = iter([("Talai", 11, "192.168.100.1"),
                         ("Talai_B", 11, "10.12.133.234")])
        with self.assertRaisesRegex(SetupError, "Upstream changed"):
            self.setup_network(adapter, check=lambda: next(sequence))
        self.assertEqual(adapter.links, {})
        self.assertEqual(self.config.read_bytes(), CONFIG)

    def test_invalid_channel_never_creates_interfaces(self):
        adapter = FakeAdapter()
        with self.assertRaises(SetupError):
            prepare_network(adapter, receipt_dir=self.receipts,
                            hostapd_path=self.config, channel=36,
                            upstream_check=lambda: ("Talai", 36))
        self.assertEqual(adapter.links, {})
        self.assertEqual(self.config.read_bytes(), CONFIG)

    def test_missing_upstream_prevents_config_change(self):
        adapter = FakeAdapter()
        with self.assertRaises(SetupError):
            self.setup_network(adapter, check=lambda: None)
        self.assertEqual(self.config.read_bytes(), CONFIG)
        self.assertEqual(adapter.links, {})


if __name__ == "__main__":
    unittest.main()
