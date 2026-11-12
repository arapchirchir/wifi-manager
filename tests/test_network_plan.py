"""Mock end-to-end WAN plus radio planning; no real system calls."""
import importlib.util
import json
from pathlib import Path
import unittest

SRC = Path(__file__).resolve().parents[1] / "scripts" / "techworld-network-plan.py"
spec = importlib.util.spec_from_file_location("techworld_network_plan", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

PHY = """Supported interface modes:
 * managed
 * AP
valid interface combinations:
 * #{ managed } <= 1, #{ AP } <= 1, total <= 2, #channels <= 1
Frequencies:
 * 2412 MHz [1] (20 dBm)
 * 2462 MHz [11] (20 dBm)
"""


class PlanTests(unittest.TestCase):
    def test_auto_detect_phy0_shared_radio_channel_11(self):
        calls = []
        results = {
            ("ip", "-j", "-4", "route", "show", "default"): json.dumps([
                {"dst": "default", "dev": "wlp109s0",
                 "gateway": "10.12.133.234", "metric": 600}
            ]),
            ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"):
                "wlp109s0:wifi:connected\n",
            ("iw", "dev", "wlp109s0", "link"):
                "Connected to 04:25:c5:9a:77:a0 (on wlp109s0)\nSSID: Talai_B\n",
            ("iw", "dev", "wlp109s0", "info"):
                "Interface wlp109s0\nwiphy 0\nchannel 11 (2462 MHz)\n",
            ("iw", "dev"): "phy#0\n Interface wlp109s0\n type managed\n",
            ("iw", "phy", "phy0", "info"): PHY,
            ("rfkill", "list"): "1: hci0: Bluetooth\n Soft blocked: no\n Hard blocked: no\n2: phy0: Wireless LAN\n Soft blocked: no\n Hard blocked: no\n",
            ("iw", "reg", "get"): "global\ncountry KE: DFS-UNSET\n",
        }

        def reader(cmd):
            calls.append(tuple(cmd))
            return results[tuple(cmd)]

        report = mod.plan(reader=reader)
        self.assertEqual(report["ap_radio"]["phy"], "phy0")
        self.assertEqual(report["ap_radio"]["channel"], 11)
        self.assertEqual(report["ap_radio"]["reason"], "shared-radio-wifi")
        self.assertFalse(report["restart_safe"])
        self.assertEqual(report["selected"]["ap_channel"], 11)
        self.assertEqual(report["candidates"][0]["ap_channel"], 11)
        self.assertFalse(report["rfkill"]["soft_blocked"])
        self.assertEqual(report["regulatory"]["countries"], ["KE"])
        self.assertFalse(report["regulatory"]["verified"])
        self.assertEqual({cmd[0] for cmd in calls}, {"ip", "nmcli", "iw", "rfkill"})


if __name__ == "__main__":
    unittest.main()
