"""Offline transaction integration tests with fake link operations."""
import json
from pathlib import Path
import tempfile
import unittest

from installer.ap_transaction import prepare, rollback, ProvisionError
from installer.creation_intent import read_intent


class Network:
    def __init__(self, failure=None):
        self.links = {}
        self.failure = failure
        self.operations = []
        self.next_index = 101

    def inspect(self, name):
        item = self.links.get(name)
        return item and {"ifindex": item["ifindex"], "kind": item["kind"]}

    def create(self, name, kind):
        self.operations.append(("create", name))
        if name == self.failure:
            raise RuntimeError("simulated creation error")
        self.links[name] = {
            "ifindex": self.next_index,
            "kind": "AP" if kind == "ap" else "bridge",
        }
        self.next_index += 1

    def read(self, cmd):
        if cmd == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps([
                {"ifname": name, "ifindex": record["ifindex"],
                 "linkinfo": {"info_kind": "bridge"} if record["kind"] == "bridge" else {}}
                for name, record in self.links.items()
            ])
        if cmd == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n\ttype AP\n"
        raise AssertionError(cmd)

    def remove(self, name, kind, index):
        self.operations.append(("remove", name))
        if self.links[name]["ifindex"] != index:
            raise AssertionError("Wrong identity")
        del self.links[name]


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / "owned"
        self.directory.mkdir(mode=0o700)

    def test_create_receipts_and_rollback(self):
        net = Network()
        report = prepare(net, self.directory)
        self.assertEqual(len(report["receipts"]), 2)
        self.assertEqual(net.inspect("ap0")["kind"], "AP")
        self.assertEqual(rollback(net, self.directory), [])
        self.assertEqual(net.links, {})
        self.assertEqual(net.operations, [
            ("create", "br-techworld"), ("create", "ap0"),
            ("remove", "ap0"), ("remove", "br-techworld"),
        ])

    def test_failed_second_creation_rolls_back_bridge(self):
        net = Network(failure="ap0")
        with self.assertRaises(ProvisionError):
            prepare(net, self.directory)
        self.assertEqual(net.links, {})

    def test_intent_is_written_before_every_interface_creation(self):
        directory = self.directory
        class GuardedNetwork(Network):
            def create(self, name, kind):
                evidence = read_intent(directory, name, kind)
                assert evidence is not None, "No durable intent before create"
                return super().create(name, kind)
        net = GuardedNetwork()
        prepare(net, self.directory)
        self.assertIsNotNone(read_intent(self.directory, "ap0", "ap"))
        self.assertIsNotNone(read_intent(self.directory, "br-techworld", "bridge"))

    def test_failed_creation_retains_precreate_intent_for_review(self):
        net = Network(failure="ap0")
        with self.assertRaises(ProvisionError):
            prepare(net, self.directory)
        self.assertIsNotNone(read_intent(self.directory, "ap0", "ap"))
        self.assertIsNone(net.inspect("ap0"))
        self.assertEqual(net.links, {})
        with self.assertRaisesRegex(ProvisionError, "intent"):
            prepare(Network(), self.directory)

    def test_crash_window_orphan_is_not_adopted_or_deleted(self):
        from installer.creation_intent import record_intent
        net = Network()
        record_intent(self.directory, "ap0", "ap")
        # Simulate a process dying between creation and ownership receipt.
        net.links["ap0"] = {"ifindex": 900, "kind": "AP"}
        with self.assertRaises(ProvisionError):
            prepare(net, self.directory)
        self.assertNotIn(("remove", "ap0"), net.operations)
        self.assertIn("ap0", net.links)

    def test_successful_rollback_retains_intent_marker(self):
        net = Network()
        prepare(net, self.directory)
        self.assertEqual(rollback(net, self.directory), [])
        self.assertIsNotNone(read_intent(self.directory, "ap0", "ap"))
        with self.assertRaisesRegex(ProvisionError, "intent"):
            prepare(Network(), self.directory)

    def test_existing_interface_is_never_adopted(self):
        net = Network()
        net.links["ap0"] = {"ifindex": 54, "kind": "AP"}
        with self.assertRaisesRegex(ProvisionError, "already exists"):
            prepare(net, self.directory)
        self.assertNotIn(("remove", "ap0"), net.operations)

    def test_stale_receipt_refuses_prepare(self):
        (self.directory / "ap0.json").write_text("stale")
        net = Network()
        with self.assertRaisesRegex(ProvisionError, "receipt"):
            prepare(net, self.directory)
        self.assertFalse(net.operations)

    def test_identity_swap_is_not_deleted(self):
        net = Network()
        prepare(net, self.directory)
        net.links["ap0"]["ifindex"] = 444
        failures = rollback(net, self.directory)
        self.assertTrue(any("Identity mismatch" in x for x in failures))
        self.assertIn("ap0", net.links)
        self.assertIn("br-techworld", net.links)

    def test_missing_receipt_does_not_authorize_delete(self):
        net = Network()
        net.links["ap0"] = {"ifindex": 55, "kind": "AP"}
        self.assertEqual(rollback(net, self.directory), [])
        self.assertIn("ap0", net.links)

    def test_partial_rollback_is_idempotent(self):
        net = Network()
        prepare(net, self.directory)
        self.assertEqual(rollback(net, self.directory), [])
        self.assertEqual(rollback(net, self.directory), [])


if __name__ == "__main__":
    unittest.main()
