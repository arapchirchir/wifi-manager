"""No live network or systemctl calls. All executors are fake."""
import json
import unittest

from installer.linux_adapters import (
    AdapterError, ServiceAdapter, LinkInspectionAdapter,
)


class ServicesTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.service = ServiceAdapter(self.fake)

    def fake(self, command):
        self.calls.append(command)
        if command[1] == "show":
            return "inactive\n"
        return ""

    def test_only_parent_can_start(self):
        self.service.start("techworld-hotspot")
        self.assertEqual(self.calls, [["systemctl", "start", "techworld-hotspot"]])
        with self.assertRaises(AdapterError):
            self.service.start("NetworkManager")
        with self.assertRaises(AdapterError):
            self.service.start("techworld-ap")
        self.assertEqual(len(self.calls), 1)

    def test_only_known_techworld_service_can_stop(self):
        self.service.stop("techworld-ap")
        with self.assertRaises(AdapterError):
            self.service.stop("docker")
        with self.assertRaises(AdapterError):
            self.service.stop("dnsmasq")
        self.assertEqual(self.calls, [["systemctl", "stop", "techworld-ap"]])

    def test_unexpected_service_state_is_fail_closed(self):
        service = ServiceAdapter(lambda _: "UNKNOWN")
        with self.assertRaises(AdapterError):
            service.state("techworld-hotspot")

    def test_state_inspection_exact_command(self):
        self.assertEqual(self.service.state("techworld-hotspot"), "inactive")
        self.assertEqual(self.calls, [
            ["systemctl", "show", "-p", "ActiveState", "--value", "techworld-hotspot"]
        ])

    def test_executor_required(self):
        with self.assertRaises(TypeError):
            ServiceAdapter(None)


class LinksTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.links = [
            {"ifname": "ap0", "ifindex": 44},
            {"ifname": "br-techworld", "ifindex": 45,
             "linkinfo": {"info_kind": "bridge"}},
        ]
        self.adapter = LinkInspectionAdapter(self.fake)

    def fake(self, command):
        self.calls.append(command)
        if command == ["ip", "-j", "-d", "link", "show"]:
            return json.dumps(self.links)
        if command == ["iw", "dev", "ap0", "info"]:
            return "Interface ap0\n\ttype AP\n"
        raise AssertionError(command)

    def test_verified_interface_types(self):
        self.assertEqual(self.adapter.inspect("ap0"),
                         {"ifindex": 44, "kind": "AP"})
        self.assertEqual(self.adapter.inspect("br-techworld"),
                         {"ifindex": 45, "kind": "bridge"})

    def test_missing_link_not_adopted(self):
        self.links = []
        self.assertIsNone(self.adapter.inspect("ap0"))

    def test_mismatched_bridge_type_stays_unverified(self):
        self.links[-1]["linkinfo"]["info_kind"] = "dummy"
        self.assertEqual(self.adapter.inspect("br-techworld")["kind"],
                         "unverified")

    def test_reused_name_invalid_index_rejected(self):
        self.links[0]["ifindex"] = "44"
        with self.assertRaises(AdapterError):
            self.adapter.inspect("ap0")

    def test_commands_cannot_mutate_interfaces(self):
        with self.assertRaises(AdapterError):
            self.adapter.create("ap0", "ap")
        with self.assertRaises(AdapterError):
            self.adapter.remove("ap0", "ap", 44)
        with self.assertRaises(AdapterError):
            self.adapter.read(["ip", "link", "delete", "ap0"])
        self.assertEqual(self.calls, [])

    def test_duplicate_names_rejected(self):
        self.links.append({"ifname": "ap0", "ifindex": 99})
        with self.assertRaises(AdapterError):
            self.adapter.inspect("ap0")

    def test_invalid_json_fails(self):
        with self.assertRaises(ValueError):
            LinkInspectionAdapter(lambda _: "invalid json").inspect("ap0")

    def test_executor_required(self):
        with self.assertRaises(TypeError):
            LinkInspectionAdapter(None)


if __name__ == "__main__":
    unittest.main()
