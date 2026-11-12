"""Mocked network discovery tests. Never touch system Wi-Fi or routing."""
import importlib.util
import json
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "installer" / "auto_network.py"
spec = importlib.util.spec_from_file_location("techworld_auto_network", MODULE)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)

IW_DEV = """phy#0
    Interface ap0
        type AP
    Interface wlp109s0
        type managed
"""
PHY_OK = """Supported interface modes:
     * managed
     * AP
valid interface combinations:
     * #{ managed } <= 1, #{ AP } <= 1, total <= 2, #channels <= 1
"""
PHY_BAD = """Supported interface modes:
     * managed
     * AP
valid interface combinations:
     * #{ managed } <= 1, total <= 1, #channels <= 1
     * #{ AP } <= 1, total <= 1, #channels <= 1
"""


class FakeNetwork:
    def __init__(self, phy=PHY_OK, routes=None, addresses=None, default=None):
        self.phy = phy
        self.routes = routes or []
        self.addresses = addresses or []
        self.default = default if default is not None else [
            {"dst": "default", "dev": "wlp109s0", "gateway": "192.168.1.1"}
        ]
        self.calls = []

    def __call__(self, args):
        self.calls.append(tuple(args))
        if args == ["iw", "dev"]:
            return IW_DEV
        if args == ["iw", "dev", "wlp109s0", "info"]:
            return "Interface wlp109s0\n channel 6 (2437 MHz), width: 20 MHz\n"
        if args == ["iw", "phy", "phy0", "info"]:
            return self.phy
        if args == ["ip", "-j", "-4", "route", "show", "default"]:
            return json.dumps(self.default)
        if args == ["ip", "-j", "-4", "route", "show", "table", "all"]:
            return json.dumps(self.routes)
        if args == ["ip", "-j", "-4", "address", "show"]:
            return json.dumps(self.addresses)
        raise AssertionError(f"unexpected command: {args}")


class DetectionTests(unittest.TestCase):
    def test_current_laptop_detects_uplink_and_channel(self):
        info = network.active_uplink(FakeNetwork())
        self.assertEqual(info["uplink"], "wlp109s0")
        self.assertEqual(info["phy"], "phy0")
        self.assertEqual(info["channel"], 6)

    def test_no_default_route_fails_closed(self):
        fake = FakeNetwork()
        fake.default = []
        with self.assertRaises(network.DiscoveryError):
            network.active_uplink(fake)

    def test_no_concurrent_ap_sta_support_fails_closed(self):
        with self.assertRaises(network.DiscoveryError):
            network.active_uplink(FakeNetwork(phy=PHY_BAD))

    def test_multiline_managed_ap_combination(self):
        phy = """Supported interface modes:
     * managed
     * AP
valid interface combinations:
     * #{ managed } <= 1, #{ AP, P2P-client, P2P-GO } <= 1,
       total <= 2, #channels <= 1
"""
        self.assertTrue(network.supports_sta_ap(phy))
        self.assertEqual(network.active_uplink(FakeNetwork(phy=phy))["channel"], 6)

    def test_disjoint_interface_modes_do_not_imply_concurrency(self):
        phy = """Supported interface modes:
     * managed
     * AP
valid interface combinations:
     * #{ managed } <= 1,
       total <= 1, #channels <= 1
     * #{ AP } <= 1,
       total <= 1, #channels <= 1
"""
        self.assertFalse(network.supports_sta_ap(phy))

    def test_same_group_one_slot_rejected(self):
        phy = """Supported interface modes:
     * managed
     * AP
valid interface combinations:
     * #{ managed, AP } <= 1, #{ P2P-client } <= 1,
       total <= 2, #channels <= 1
"""
        self.assertFalse(network.supports_sta_ap(phy))

    def test_first_unused_subnet_selected(self):
        fake = FakeNetwork(routes=[
            {"dst": "10.77.77.0/24", "dev": "docker0"},
            {"dst": "192.168.1.0/24", "dev": "wlp109s0"},
        ])
        result = network.discover("clean", fake)
        self.assertEqual(result["gateway"], "10.77.78.1/24")
        self.assertEqual(result["dhcp_start"], "10.77.78.50")

    def test_preserve_existing_hotspot_gateway(self):
        fake = FakeNetwork(
            routes=[{"dst": "10.77.77.0/24", "dev": "br-techworld"}],
            addresses=[{
                "ifname": "br-techworld",
                "addr_info": [{
                    "family": "inet", "local": "10.77.77.1", "prefixlen": 24
                }],
            }],
        )
        result = network.discover("adoption_required", fake)
        self.assertEqual(result["gateway"], "10.77.77.1/24")
        self.assertTrue(result["preserve_existing"])

    def test_overlapping_external_route_blocks_existing_gateway(self):
        fake = FakeNetwork(
            routes=[{"dst": "10.77.77.0/24", "dev": "br-techworld"},
                    {"dst": "10.77.0.0/16", "dev": "tun0"}],
            addresses=[{
                "ifname": "br-techworld",
                "addr_info": [{
                    "family": "inet", "local": "10.77.77.1", "prefixlen": 24
                }],
            }],
        )
        with self.assertRaises(network.DiscoveryError):
            network.discover("adoption_required", fake)

    def test_existing_bridge_not_reused_for_clean_install(self):
        fake = FakeNetwork(
            routes=[{"dst": "10.77.77.0/24", "dev": "br-techworld"}],
            addresses=[{
                "ifname": "br-techworld",
                "addr_info": [{
                    "family": "inet", "local": "10.77.77.1", "prefixlen": 24
                }],
            }],
        )
        result = network.discover("clean", fake)
        self.assertEqual(result["gateway"], "10.77.78.1/24")

    def test_dhcp_auto_pool_excludes_gateway(self):
        start, end = network.auto_pool("10.77.77.100/24")
        self.assertFalse(start <= "10.77.77.100" <= end)

    def test_all_candidates_conflict_fails_closed(self):
        fake = FakeNetwork(routes=[{"dst": "10.0.0.0/8", "dev": "tun0"},
                                   {"dst": "172.16.0.0/12", "dev": "tun0"},
                                   {"dst": "192.168.0.0/16", "dev": "tun0"}])
        with self.assertRaises(network.DiscoveryError):
            network.discover("clean", fake)

    def test_read_only_inspection_calls(self):
        fake = FakeNetwork()
        network.discover("clean", fake)
        self.assertTrue(all(command[0] in ("iw", "ip") for command in fake.calls))


if __name__ == "__main__":
    unittest.main()
