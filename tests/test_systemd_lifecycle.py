"""Offline tests for service source analysis and blocked stop actions."""
from pathlib import Path
import unittest

from installer.linux_adapters import UNITS
from installer.systemd_lifecycle import (
    LifecycleError, STOP_ORDER, _directives, load_repository_units,
    review_unit_sources, stop_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def test_repository_identifies_unsafe_ap_stop(self):
        result = load_repository_units(ROOT)
        self.assertFalse(result["source_safe_to_deploy"])
        self.assertFalse(result["installed_units_verified"])
        self.assertTrue(any("stop path unverified" in x for x in result["blockers"]))
        self.assertTrue(any("legacy prepare" in x for x in result["blockers"]))

    def test_boot_activation_risks_identified(self):
        blockers = load_repository_units(ROOT)["blockers"]
        self.assertTrue(any("boot activation" in x for x in blockers))
        self.assertTrue(any("independently enableable" in x for x in blockers))

    def test_stop_order_places_ap_last(self):
        self.assertEqual(set(STOP_ORDER), UNITS)
        self.assertEqual(STOP_ORDER[0], "techworld-hotspot")
        self.assertEqual(STOP_ORDER[-1], "techworld-ap")
        self.assertLess(STOP_ORDER.index("techworld-hostapd"),
                        STOP_ORDER.index("techworld-ap"))

    def test_missing_unit_blocks_analysis(self):
        with self.assertRaises(LifecycleError):
            review_unit_sources({"techworld-ap": "[Service]\nExecStop=/bin/true"})

    def test_unexpected_unit_blocks_analysis(self):
        data = {u: "[Service]\nExecStart=/bin/true" for u in UNITS}
        data["NetworkManager"] = "[Service]\nExecStart=/bin/true"
        with self.assertRaises(LifecycleError):
            review_unit_sources(data)

    def test_source_without_legacy_patterns_still_not_approved(self):
        data = {u: "[Service]\nExecStart=/bin/true" for u in UNITS}
        result = review_unit_sources(data)
        self.assertEqual(result["blockers"], [])
        self.assertFalse(result["source_safe_to_deploy"])

    def test_stop_post_override_in_source_blocks(self):
        data = {u: "[Service]\nExecStart=/bin/true" for u in UNITS}
        data["techworld-ap"] += "\nExecStopPost=/bin/true\n"
        result = review_unit_sources(data)
        self.assertTrue(any("ExecStopPost" in x for x in result["blockers"]))

    def test_malformed_unit_fails_closed(self):
        for source in ("", "ExecStop=/bin/true", "[Service]\nExecStop=a\\\nb",
                       "[Unknown]\nExecStart=/bin/true"):
            with self.subTest(source=source):
                with self.assertRaises(LifecycleError):
                    _directives(source)

    def test_unverified_installed_units_never_generate_stop_plan(self):
        states = {u: "active" for u in UNITS}
        with self.assertRaisesRegex(LifecycleError, "not verified"):
            stop_plan(states)
        with self.assertRaisesRegex(LifecycleError, "not implemented"):
            stop_plan(states, installed_units_verified=True)

    def test_incomplete_state_inventory_blocks(self):
        with self.assertRaises(LifecycleError):
            stop_plan({"techworld-ap": "active"}, installed_units_verified=True)


if __name__ == "__main__":
    unittest.main()
