"""Offline tests: never touch real host networking."""
import unittest
from installer.resource_ownership import cleanup_plan, validate_inventory


def record():
    return {
        "version": 1,
        "interfaces": [
            {"name": "ap0", "kind": "ap", "ifindex": 101},
            {"name": "br-techworld", "kind": "bridge", "ifindex": 102},
        ],
    }


class OwnershipTests(unittest.TestCase):
    def test_verified_interfaces_removed_in_safe_order(self):
        report = cleanup_plan(record(), {
            "ap0": {"ifindex": 101, "kind": "AP"},
            "br-techworld": {"ifindex": 102, "kind": "bridge"},
        })
        self.assertEqual([item[0] for item in report["remove"]], ["ap0", "br-techworld"])
        self.assertEqual(report["refuse"], [])

    def test_absent_interfaces_are_noop(self):
        self.assertEqual(cleanup_plan(record(), {})["remove"], [])

    def test_reused_ap_name_with_new_ifindex_not_removed(self):
        report = cleanup_plan(record(), {
            "ap0": {"ifindex": 203, "kind": "AP"},
            "br-techworld": {"ifindex": 102, "kind": "bridge"},
        })
        self.assertEqual(report["remove"], [])
        self.assertTrue(report["refuse"])

    def test_name_match_but_wrong_interface_type_not_removed(self):
        report = cleanup_plan(record(), {
            "ap0": {"ifindex": 101, "kind": "managed"},
            "br-techworld": {"ifindex": 102, "kind": "bridge"},
        })
        self.assertEqual(report["remove"], [])

    def test_bridge_mismatch_does_not_remove_bridge(self):
        report = cleanup_plan(record(), {
            "ap0": {"ifindex": 101, "kind": "AP"},
            "br-techworld": {"ifindex": 102, "kind": "dummy"},
        })
        self.assertEqual([item[0] for item in report["remove"]], ["ap0"])

    def test_invalid_missing_inventory_rejected(self):
        with self.assertRaises(ValueError):
            cleanup_plan(None, {})

    def test_duplicate_ifindex_rejected(self):
        inv = record()
        inv["interfaces"][1]["ifindex"] = 101
        with self.assertRaises(ValueError):
            validate_inventory(inv)

    def test_forged_invalid_name_rejected(self):
        inv = record()
        inv["interfaces"][0]["name"] = "--delete"
        with self.assertRaises(ValueError):
            validate_inventory(inv)


if __name__ == "__main__":
    unittest.main()
