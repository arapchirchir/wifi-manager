"""No host-network changes: WAN routing selection regression tests."""
import json
import unittest

from installer.uplink_selection import inspect, select_route, SelectionError


def wifi(ssid="Talai", channel=11, phy="phy0"):
    return {"wlp109s0": {"ssid": ssid, "channel": channel, "phy": phy}}


def routes(*items):
    return [{"dst": "default", "dev": dev, "gateway": gateway, "metric": metric}
            for dev, gateway, metric in items]


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.devices = {
            "wlp109s0": {"type": "wifi", "connected": True},
            "enp0s31f6": {"type": "ethernet", "connected": True},
        }

    def test_wifi_talai(self):
        result = select_route(routes(("wlp109s0", "192.168.100.1", 600)),
                              self.devices, wifi(), ap_radio="phy0")
        self.assertEqual(result["selected"]["ssid"], "Talai")
        self.assertEqual(result["selected"]["ap_channel"], 11)

    def test_wifi_talai_b_changed_gateway(self):
        result = select_route(routes(("wlp109s0", "10.12.133.234", 600)),
                              self.devices, wifi("Talai_B"), ap_radio="phy0")
        self.assertEqual(result["selected"]["gateway"], "10.12.133.234")
        self.assertEqual(result["selected"]["ssid"], "Talai_B")

    def test_ethernet_is_primary_by_metric(self):
        result = select_route(
            routes(("wlp109s0", "10.12.133.234", 600),
                   ("enp0s31f6", "192.168.1.1", 100)),
            self.devices, wifi(), ap_radio="phy0")
        self.assertEqual(result["selected"]["kind"], "ethernet")
        self.assertIsNone(result["selected"]["ap_channel"])

    def test_ethernet_disconnected_uses_wifi(self):
        self.devices["enp0s31f6"]["connected"] = False
        result = select_route(
            routes(("enp0s31f6", "192.168.1.1", 100),
                   ("wlp109s0", "10.12.133.234", 600)),
            self.devices, wifi("Talai_B"))
        self.assertEqual(result["selected"]["kind"], "wifi")

    def test_both_ethernet_and_wifi_down_fails_closed(self):
        self.devices["enp0s31f6"]["connected"] = False
        self.devices["wlp109s0"]["connected"] = False
        with self.assertRaises(SelectionError):
            select_route(routes(("wlp109s0", "10.12.133.234", 600)),
                         self.devices, wifi())

    def test_two_same_metric_ethernet_routes_are_ambiguous(self):
        self.devices["eth2"] = {"type": "ethernet", "connected": True}
        with self.assertRaisesRegex(SelectionError, "Ambiguous"):
            select_route(routes(("enp0s31f6", "192.168.1.1", 100),
                                ("eth2", "10.0.0.1", 100)),
                         self.devices, wifi())

    def test_equal_metric_ethernet_preferred_over_wifi(self):
        result = select_route(
            routes(("wlp109s0", "10.12.133.234", 100),
                   ("enp0s31f6", "192.168.1.1", 100)),
            self.devices, wifi())
        self.assertEqual(result["selected"]["kind"], "ethernet")

    def test_invalid_gateway_ignored(self):
        result = select_route(
            routes(("enp0s31f6", "not-an-ip", 10),
                   ("wlp109s0", "192.168.100.1", 600)),
            self.devices, wifi())
        self.assertEqual(result["selected"]["kind"], "wifi")

    def test_missing_wifi_association_rejected(self):
        with self.assertRaises(SelectionError):
            select_route(routes(("wlp109s0", "192.168.100.1", 600)),
                         self.devices, {})

    def test_unsupported_shared_radio_channel_rejected(self):
        with self.assertRaises(SelectionError):
            select_route(routes(("wlp109s0", "192.168.100.1", 600)),
                         self.devices, wifi(channel=36), ap_radio="phy0")

    def test_never_claims_internet_verified_or_restart_ready(self):
        result = select_route(routes(("enp0s31f6", "192.168.1.1", 100)),
                              self.devices, {})
        self.assertFalse(result["selected"]["internet_verified"])
        self.assertFalse(result["restart_safe"])
        self.assertTrue(result["requires_internet_probe"])

    def test_readonly_integrated_inspection(self):
        called = []
        replies = {
            ("ip", "-j", "-4", "route", "show", "default"):
                json.dumps(routes(("wlp109s0", "10.12.133.234", 600))),
            ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"):
                "wlp109s0:wifi:connected\nenp0s31f6:ethernet:disconnected\n",
            ("iw", "dev", "wlp109s0", "link"):
                "Connected to 04:25:c5:9a:77:a0 (on wlp109s0)\nSSID: Talai_B\n",
            ("iw", "dev", "wlp109s0", "info"):
                "Interface wlp109s0\nwiphy 0\nchannel 11 (2462 MHz)\n",
        }
        def reader(command):
            called.append(command)
            return replies[tuple(command)]
        result = inspect(reader=reader, ap_radio="phy0")
        self.assertEqual(result["selected"]["ap_channel"], 11)
        self.assertEqual({c[0] for c in called}, {"ip", "nmcli", "iw"})


if __name__ == "__main__":
    unittest.main()
