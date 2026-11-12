"""Offline recovery reconciliation tests. No real networking commands."""
import json
from pathlib import Path
import tempfile
import unittest

from installer.creation_intent import record_intent
from installer.ownership_receipt import write_new_receipt
from installer.recovery_journal import begin_journal
from installer.recovery_reconciliation import reconcile, ReconciliationError


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / "private"
        self.folder.mkdir(mode=0o700)
        self.links = {}

    def reader(self, command):
        if command == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps([
                {"ifname": name, "ifindex": details[0],
                 "linkinfo": {"info_kind": "bridge"} if details[1] == "bridge" else {}}
                for name, details in self.links.items()
            ])
        if command == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n type AP\n"
        raise AssertionError(command)

    def assess(self):
        return reconcile(self.folder, reader=self.reader)

    def receipt(self, name="ap0", kind="ap", index=42):
        write_new_receipt(self.folder / (name + ".json"), {
            "version": 1,
            "interfaces": [{"name": name, "kind": kind, "ifindex": index}]
        })

    def test_clean_snapshot_never_authorizes_restart(self):
        output = self.assess()
        self.assertFalse(output["manual_review_required"])
        self.assertFalse(output["safe_to_restart"])
        self.assertFalse(output["automatic_cleanup_allowed"])

    def test_journal_only_requires_review(self):
        begin_journal(self.folder, 11)
        output = self.assess()
        self.assertTrue(output["manual_review_required"])
        self.assertEqual(output["journal_state"], "pending")

    def test_crash_window_orphan_is_not_adopted(self):
        record_intent(self.folder, "ap0", "ap")
        self.links["ap0"] = (42, "ap")
        output = self.assess()
        self.assertEqual(output["interfaces"]["ap0"]["status"],
                         "intent_without_receipt_live_interface")
        self.assertFalse(output["ownership_proven"])
        self.assertFalse(output["automatic_cleanup_allowed"])

    def test_crash_before_create_intent_still_requires_review(self):
        record_intent(self.folder, "ap0", "ap")
        output = self.assess()
        self.assertEqual(output["interfaces"]["ap0"]["status"],
                         "intent_without_receipt_interface_absent")
        self.assertTrue(output["manual_review_required"])

    def test_unrecorded_interface_not_adopted(self):
        self.links["ap0"] = (91, "ap")
        output = self.assess()
        self.assertEqual(output["interfaces"]["ap0"]["status"],
                         "unrecorded_live_interface")
        self.assertFalse(output["ownership_proven"])

    def test_receipt_without_intent_is_anomaly(self):
        self.receipt()
        self.links["ap0"] = (42, "ap")
        self.assertEqual(self.assess()["interfaces"]["ap0"]["status"],
                         "receipt_without_intent")

    def test_matched_receipt_not_proof_of_ownership(self):
        record_intent(self.folder, "ap0", "ap")
        self.receipt()
        self.links["ap0"] = (42, "ap")
        output = self.assess()
        self.assertEqual(output["interfaces"]["ap0"]["status"],
                         "receipt_matches_live_snapshot")
        self.assertFalse(output["ownership_proven"])
        self.assertTrue(output["manual_review_required"])

    def test_reused_interface_index_mismatch(self):
        record_intent(self.folder, "ap0", "ap")
        self.receipt()
        self.links["ap0"] = (93, "ap")
        self.assertEqual(self.assess()["interfaces"]["ap0"]["status"],
                         "receipt_live_identity_mismatch")

    def test_recorded_but_absent(self):
        record_intent(self.folder, "ap0", "ap")
        self.receipt()
        self.assertEqual(self.assess()["interfaces"]["ap0"]["status"],
                         "receipt_recorded_interface_absent")

    def test_wrong_reserved_receipt_name_refused(self):
        write_new_receipt(self.folder / "ap0.json", {
            "version": 1,
            "interfaces": [{"name": "wlan0", "kind": "ap", "ifindex": 42}]
        })
        with self.assertRaises(ReconciliationError):
            self.assess()

    def test_duplicate_recorded_ifindices_refused(self):
        self.receipt("ap0", "ap", 42)
        self.receipt("br-techworld", "bridge", 42)
        with self.assertRaises(ReconciliationError):
            self.assess()

    def test_symlink_receipt_refused(self):
        (self.folder / "ap0.json").symlink_to("/etc/passwd")
        with self.assertRaises(OSError):
            self.assess()

    def test_malformed_network_inventory_refused(self):
        with self.assertRaises(ValueError):
            reconcile(self.folder, reader=lambda _: "invalid json")

    def test_reader_required(self):
        with self.assertRaises(TypeError):
            reconcile(self.folder, reader=None)

    def test_foreign_bridge_is_not_touched(self):
        self.links["br-techworld"] = (99, "bridge")
        result = self.assess()
        self.assertEqual(result["interfaces"]["br-techworld"]["status"],
                         "unrecorded_live_interface")
        self.assertFalse(result["automatic_cleanup_allowed"])


if __name__ == "__main__":
    unittest.main()
