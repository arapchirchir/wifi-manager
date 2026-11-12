"""Offline radio and transition tests, no system network operations."""
import unittest
from installer.radio_selection import parse_radios, allowed_legacy_channels, choose_radio, RadioError
from installer.restart_decision import transition


FREQUENCIES = """Frequencies:
    * 2412 MHz [1] (20.0 dBm)
    * 2437 MHz [6] (20.0 dBm)
    * 2462 MHz [11] (20.0 dBm)
    * 2467 MHz [12] (disabled)
    * 5180 MHz [36] (no IR)
"""

SHARED = """Supported interface modes:
    * managed
    * AP
valid interface combinations:
    * #{ managed } <= 1, #{ AP } <= 1, total <= 2, #channels <= 1
""" + FREQUENCIES

AP_ONLY = """Supported interface modes:
    * AP
""" + FREQUENCIES

NO_AP = """Supported interface modes:
    * managed
""" + FREQUENCIES


def selected(kind="wifi", phy="phy0", channel=11):
    return {"kind": kind, "interface": "wlp109s0" if kind == "wifi" else "eth0",
            "gateway": "10.12.133.234", "ssid": "Talai_B" if kind == "wifi" else None,
            "channel": channel if kind == "wifi" else None, "phy": phy if kind == "wifi" else None}


def report(ssid="Talai", channel=11, kind="wifi", gateway="192.168.100.1"):
    route = selected(kind=kind, channel=channel)
    route["gateway"] = gateway
    route["ssid"] = ssid if kind == "wifi" else None
    return {"selected": route, "ap_radio": {"phy": "phy0", "channel": channel}}


class RadioSelectionTests(unittest.TestCase):
    def test_parse_phy_and_managed_interface(self):
        radios = parse_radios("phy#0\n Interface wlp109s0\n type managed\nphy#1\n Interface ap1\n type AP\n")
        self.assertEqual(radios["phy0"]["managed"], ["wlp109s0"])
        self.assertEqual(radios["phy1"]["managed"], [])

    def test_regulatory_disabled_channels_ignored(self):
        self.assertEqual(allowed_legacy_channels(FREQUENCIES), [1, 6, 11])

    def test_decimal_mhz_lines_from_real_iw_output(self):
        frequencies = """Band 1:
            * 2412.0 MHz [1] (20.0 dBm)
            * 2437.0 MHz [6] (20.0 dBm)
            * 2462.0 MHz [11] (20.0 dBm)
            * 2467.0 MHz [12] (disabled)
            * 5180.0 MHz [36] (no IR)
        """
        self.assertEqual(allowed_legacy_channels(frequencies), [1, 6, 11])

    def test_decimal_mhz_shared_radio_selects_channel_eleven(self):
        info = SHARED.replace("2412 MHz", "2412.0 MHz").replace(
            "2437 MHz", "2437.0 MHz"
        ).replace("2462 MHz", "2462.0 MHz")
        result = choose_radio({"phy0": {"managed": ["wlp109s0"]}},
                              selected(channel=11), {"phy0": info})
        self.assertEqual(result["channel"], 11)

    def test_fractional_frequency_not_accepted_as_different_channel(self):
        self.assertEqual(allowed_legacy_channels(
            " * 2462.5 MHz [11] (20.0 dBm)\n"
        ), [])

    def test_single_radio_matches_upstream_channel(self):
        radios = {"phy0": {"managed": ["wlp109s0"]}}
        result = choose_radio(radios, selected(), {"phy0": SHARED})
        self.assertEqual(result["channel"], 11)
        self.assertEqual(result["reason"], "shared-radio-wifi")
        self.assertFalse(result["regulatory_verified"])

    def test_single_radio_unsupported_concurrency_rejected(self):
        with self.assertRaises(RadioError):
            choose_radio({"phy0": {"managed": ["wlp109s0"]}},
                         selected(), {"phy0": NO_AP})

    def test_unsupported_shared_channel_rejected(self):
        with self.assertRaises(RadioError):
            choose_radio({"phy0": {"managed": ["wlp109s0"]}},
                         selected(channel=36), {"phy0": SHARED})

    def test_ethernet_can_use_idle_ap_radio(self):
        result = choose_radio({"phy1": {"managed": []}},
                              selected("ethernet"), {"phy1": AP_ONLY})
        self.assertEqual(result["phy"], "phy1")
        self.assertEqual(result["channel"], 1)

    def test_ethernet_refuses_busy_managed_radio(self):
        with self.assertRaises(RadioError):
            choose_radio({"phy0": {"managed": ["wlp109s0"]}},
                         selected("ethernet"), {"phy0": AP_ONLY})

    def test_ambiguous_radios_fail_closed(self):
        with self.assertRaisesRegex(RadioError, "Multiple"):
            choose_radio({"phy0": {"managed": []}, "phy1": {"managed": []}},
                         selected("ethernet"), {"phy0": AP_ONLY, "phy1": AP_ONLY})

    def test_explicit_radio_resolves_ambiguity(self):
        result = choose_radio({"phy0": {"managed": []}, "phy1": {"managed": []}},
                              selected("ethernet"), {"phy0": AP_ONLY, "phy1": AP_ONLY},
                              preferred="phy1")
        self.assertEqual(result["phy"], "phy1")


class RestartDecisionTests(unittest.TestCase):
    def test_unchanged_network_needs_no_reconfiguration(self):
        result = transition(report(), report())
        self.assertEqual(result["decision"], "unchanged")
        self.assertEqual(result["changes"], {})

    def test_wifi_network_and_gateway_change_requires_approval(self):
        result = transition(report(), report("Talai_B", gateway="10.12.133.234"))
        self.assertEqual(result["decision"], "needs_supervised_reconfiguration")
        self.assertIn("ssid", result["changes"])
        self.assertIn("gateway", result["changes"])
        self.assertTrue(result["requires_approval"])
        self.assertFalse(result["restart_safe"])

    def test_wifi_to_ethernet_requires_approval(self):
        result = transition(report(), report(kind="ethernet"))
        self.assertEqual(result["decision"], "needs_supervised_reconfiguration")
        self.assertIn("kind", result["changes"])

    def test_channel_change_requires_approval(self):
        result = transition(report(), report(channel=6))
        self.assertIn("ap_channel", result["changes"])

    def test_initial_setup_requires_approval(self):
        self.assertEqual(transition(None, report())["decision"], "initial_setup")


if __name__ == "__main__":
    unittest.main()
