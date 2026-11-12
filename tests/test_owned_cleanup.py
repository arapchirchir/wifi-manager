"""Offline coverage of Techworld-only failure cleanup."""
import importlib.util
import json
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "techworld-supervised-start.py"
spec = importlib.util.spec_from_file_location("techworld_supervised_cleanup", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeServices:
    def __init__(self, states):
        self.states = dict(states)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[:2] == ["systemctl", "show"]:
            return self.states[cmd[-1]] + "\n"
        if cmd[:2] == ["systemctl", "stop"]:
            self.states[cmd[-1]] = "inactive"
            return ""
        raise AssertionError(cmd)


class CleanupTests(unittest.TestCase):
    def test_partial_failure_stops_orphan_child_not_shared_dnsmasq(self):
        states = {unit: "inactive" for unit in mod.ALL_UNITS}
        states["techworld-dhcp"] = "active"
        states["techworld-hostapd"] = "active"
        fake = FakeServices(states)
        errors = []
        remaining = mod.stop_owned_after_failed_start(fake, errors)
        self.assertEqual(remaining, {})
        self.assertEqual(errors, [])
        stops = [cmd[-1] for cmd in fake.calls if cmd[1] == "stop"]
        self.assertIn("techworld-dhcp", stops)
        self.assertIn("techworld-hostapd", stops)
        self.assertNotIn("dnsmasq", stops)
        self.assertNotIn("NetworkManager", stops)

    def test_all_inactive_needs_no_stop(self):
        fake = FakeServices({unit: "inactive" for unit in mod.ALL_UNITS})
        self.assertEqual(mod.stop_owned_after_failed_start(fake, []), {})
        self.assertFalse(any(cmd[1] == "stop" for cmd in fake.calls))


if __name__ == "__main__":
    unittest.main()
