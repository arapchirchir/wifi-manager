"""Offline tests of receipt-checked cleanup. No real interface deletion."""
import json
from pathlib import Path
import tempfile
import unittest

from installer.owned_cleanup import observe, safe_cleanup
from installer.ownership_receipt import write_new_receipt


class FakeNetwork:
    def __init__(self):
        self.links = {
            "ap0": {"ifindex": 101, "ifname": "ap0"},
            "br-techworld": {"ifindex": 102, "ifname": "br-techworld",
                             "linkinfo": {"info_kind": "bridge"}},
        }
        self.deleted = []
        self.calls = []

    def read(self, cmd):
        self.calls.append(cmd)
        if cmd == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps(list(self.links.values()))
        if cmd == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n\ttype AP\n"
        raise AssertionError(cmd)

    def mutate(self, name, kind, index):
        self.deleted.append((name, kind, index))
        del self.links[name]


class CleanupTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / "private"
        folder.mkdir(mode=0o700)
        self.receipt = folder / "interfaces.json"
        write_new_receipt(self.receipt, {
            "version": 1, "interfaces": [
                {"name": "ap0", "kind": "ap", "ifindex": 101},
                {"name": "br-techworld", "kind": "bridge", "ifindex": 102},
            ],
        })

    def test_preview_never_mutates(self):
        net = FakeNetwork()
        result = safe_cleanup(self.receipt, reader=net.read)
        self.assertEqual(len(result["plan"]["remove"]), 2)
        self.assertFalse(result["executed"])
        self.assertEqual(net.deleted, [])

    def test_execute_without_mutator_refuses(self):
        net = FakeNetwork()
        result = safe_cleanup(self.receipt, execute=True, reader=net.read)
        self.assertTrue(result["errors"])
        self.assertEqual(net.deleted, [])

    def test_verified_delete_ap_before_bridge(self):
        net = FakeNetwork()
        result = safe_cleanup(self.receipt, execute=True, reader=net.read,
                              mutator=net.mutate)
        self.assertEqual(result["errors"], [])
        self.assertEqual([name for name, _, _ in net.deleted],
                         ["ap0", "br-techworld"])

    def test_reused_name_prevents_any_deletion(self):
        net = FakeNetwork()
        net.links["ap0"]["ifindex"] = 222
        result = safe_cleanup(self.receipt, execute=True, reader=net.read,
                              mutator=net.mutate)
        self.assertTrue(result["errors"])
        self.assertEqual(net.deleted, [])

    def test_missing_receipt_fails_closed(self):
        with self.assertRaises(FileNotFoundError):
            safe_cleanup(self.receipt.with_name("missing.json"), reader=FakeNetwork().read)

    def test_recheck_detects_race_before_delete(self):
        net = FakeNetwork()
        calls = [0]
        def race(cmd):
            if cmd == ["ip", "-j", "-d", "link", "show"]:
                calls[0] += 1
                if calls[0] == 2:
                    net.links["ap0"]["ifindex"] = 777
            return net.read(cmd)
        result = safe_cleanup(self.receipt, execute=True, reader=race,
                              mutator=net.mutate)
        self.assertTrue(result["errors"])
        self.assertEqual(net.deleted, [])

    def test_unrelated_bridge_member_prevents_bridge_deletion(self):
        net = FakeNetwork()
        net.links["veth-other"] = {
            "ifname": "veth-other", "ifindex": 900,
            "master": "br-techworld",
        }
        result = safe_cleanup(self.receipt, execute=True, reader=net.read,
                              mutator=net.mutate)
        self.assertIn(("ap0", "ap", 101), net.deleted)
        self.assertIn("br-techworld", net.links)
        self.assertTrue(any("attached interfaces" in error
                            for error in result["errors"]))

    def test_attached_ap_not_deleted_on_identity_mismatch(self):
        net = FakeNetwork()
        net.links["ap0"]["ifindex"] = 501
        net.links["ap0"]["master"] = "br-techworld"
        result = safe_cleanup(self.receipt, execute=True, reader=net.read,
                              mutator=net.mutate)
        self.assertTrue(result["errors"])
        self.assertEqual(net.deleted, [])

    def test_bridge_membership_query_failure_retains_bridge(self):
        net = FakeNetwork()
        calls = [0]
        def read(cmd):
            if cmd == ["ip", "-j", "-d", "link", "show"]:
                calls[0] += 1
                if calls[0] >= 5:
                    raise RuntimeError("link inspection unavailable")
            return net.read(cmd)
        # A monitoring failure must never permit deleting the bridge.
        # This injected reader raises before the bridge is removed.
        result = safe_cleanup(self.receipt, execute=True, reader=read,
                              mutator=net.mutate)
        self.assertTrue(any("Cannot verify bridge membership" in error
                            for error in result["errors"]))
        self.assertIn("br-techworld", net.links)

    def test_observation_detects_bridge_and_ap(self):
        net = FakeNetwork()
        result = observe(["ap0", "br-techworld"], reader=net.read)
        self.assertEqual(result["ap0"]["kind"], "AP")
        self.assertEqual(result["br-techworld"]["kind"], "bridge")


if __name__ == "__main__":
    unittest.main()
