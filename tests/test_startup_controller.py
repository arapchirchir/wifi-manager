"""No live commands: integrated startup and rollback simulations."""
import json
from pathlib import Path
import tempfile
import unittest

from installer.startup_controller import startup, StartupError, TECHWORLD_UNITS


CONF = b"interface=ap0\nssid=Techworld-WiFi\nhw_mode=g\nchannel=6\n"


class FakeNetwork:
    def __init__(self, fail=None):
        self.links = {}
        self.calls = []
        self.fail = fail
        self.next_index = 100

    def inspect(self, name):
        return self.links.get(name)

    def create(self, name, kind):
        self.calls.append(("create", name))
        if self.fail == name:
            raise RuntimeError("failed interface creation")
        self.next_index += 1
        self.links[name] = {
            "ifindex": self.next_index,
            "kind": "AP" if kind == "ap" else "bridge",
        }

    def remove(self, name, kind, index):
        self.calls.append(("remove", name))
        assert self.links[name]["ifindex"] == index
        del self.links[name]

    def read(self, command):
        if command == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps([
                {"ifname": n, "ifindex": data["ifindex"],
                 "linkinfo": {"info_kind": "bridge"} if data["kind"] == "bridge" else {}}
                for n, data in self.links.items()
            ])
        if command == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n type AP\n"
        raise AssertionError(command)


class FakeServices:
    def __init__(self, failure=False, stop_failure=False):
        self.states = {unit: "inactive" for unit in TECHWORLD_UNITS}
        self.calls = []
        self.failure = failure
        self.stop_failure = stop_failure

    def state(self, unit):
        assert unit in TECHWORLD_UNITS
        return self.states[unit]

    def start(self, unit):
        self.calls.append(("start", unit))
        self.states[unit] = "active"
        self.states["techworld-ap"] = "active"
        if self.failure:
            raise RuntimeError("partial systemd failure")

    def stop(self, unit):
        self.calls.append(("stop", unit))
        if self.stop_failure and unit == "techworld-hotspot":
            raise RuntimeError("stop unsuccessful")
        self.states[unit] = "inactive"


class StartTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.receipts = self.root / "private"
        self.receipts.mkdir(mode=0o700)
        self.config = self.root / "hostapd.conf"
        self.config.write_bytes(CONF)
        self.network = FakeNetwork()
        self.services = FakeServices()

    def run_start(self, **kwargs):
        opts = dict(
            receipt_dir=self.receipts,
            hostapd_path=self.config,
            channel=11,
            upstream_check=lambda: ("Talai", 11, "192.168.100.1"),
            post_check=lambda: True,
        )
        opts.update(kwargs)
        return startup(self.network, self.services, **opts)

    def test_success_starts_only_techworld_parent(self):
        result = self.run_start()
        self.assertTrue(result["started"])
        self.assertFalse(result["restart_safe"])
        self.assertEqual(self.services.calls, [("start", "techworld-hotspot")])
        self.assertIn(b"channel=11", self.config.read_bytes())

    def test_failed_postcheck_restores_services_config_and_interfaces(self):
        with self.assertRaisesRegex(StartupError, "recovery completed"):
            self.run_start(post_check=lambda: False)
        self.assertEqual(self.network.links, {})
        self.assertEqual(self.config.read_bytes(), CONF)
        self.assertEqual(self.services.states["techworld-hotspot"], "inactive")
        self.assertNotIn(("stop", "NetworkManager"), self.services.calls)

    def test_partial_start_failure_recovers_child_service(self):
        self.services.failure = True
        with self.assertRaisesRegex(StartupError, "recovery completed"):
            self.run_start()
        self.assertEqual(self.network.links, {})
        self.assertEqual(self.config.read_bytes(), CONF)
        self.assertEqual(self.services.states["techworld-ap"], "inactive")

    def test_stop_failure_retains_interfaces(self):
        self.services.stop_failure = True
        with self.assertRaisesRegex(StartupError, "recovery incomplete"):
            self.run_start(post_check=lambda: False)
        self.assertIn("ap0", self.network.links)

    def test_active_existing_service_not_touched(self):
        self.services.states["opennds"] = "active"
        with self.assertRaisesRegex(StartupError, "not fully inactive"):
            self.run_start()
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.config.read_bytes(), CONF)

    def test_existing_interface_not_adopted(self):
        self.network.links["ap0"] = {"ifindex": 500, "kind": "AP"}
        with self.assertRaisesRegex(StartupError, "Unowned interface"):
            self.run_start()
        self.assertEqual(self.services.calls, [])

    def test_upstream_change_before_start_rolls_back(self):
        snapshots = iter([
            ("Talai", 11), ("Talai", 11), ("Talai", 11), ("Talai_B", 11)
        ])
        with self.assertRaisesRegex(StartupError, "Upstream changed"):
            self.run_start(upstream_check=lambda: next(snapshots))
        self.assertEqual(self.network.links, {})
        self.assertEqual(self.config.read_bytes(), CONF)
        self.assertEqual(self.services.calls, [])

    def test_channel_mismatch_refuses_before_changes(self):
        with self.assertRaisesRegex(StartupError, "channel disagrees"):
            self.run_start(channel=6)
        self.assertEqual(self.config.read_bytes(), CONF)
        self.assertEqual(self.services.calls, [])

    def test_interface_creation_failure_keeps_service_stopped(self):
        self.network.fail = "ap0"
        with self.assertRaises(StartupError):
            self.run_start()
        self.assertEqual(self.network.links, {})
        self.assertEqual(self.services.calls, [])
        self.assertEqual(self.config.read_bytes(), CONF)


if __name__ == "__main__":
    unittest.main()
