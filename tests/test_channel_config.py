"""Pure hostapd channel renderer regression tests."""
import importlib.util
import unittest
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "installer" / "channel_config.py"
spec = importlib.util.spec_from_file_location("channel_config", FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class RenderChannelTests(unittest.TestCase):
    def test_uses_detected_channel_eleven(self):
        original = "interface=ap0\nssid=Wireless\nchannel=6\n"
        self.assertEqual(mod.render_channel(original, 11),
                         "interface=ap0\nssid=Wireless\nchannel=11\n")

    def test_idempotent_channel_sync(self):
        original = "interface=ap0\nchannel=11\n"
        self.assertEqual(mod.render_channel(original, 11), original)

    def test_does_not_modify_unrelated_hostapd_fields(self):
        original = "interface=ap0\nssid=Wireless\nhw_mode=g\nchannel=6\n"
        new = mod.render_channel(original, 11)
        self.assertIn("ssid=Wireless", new)
        self.assertIn("hw_mode=g", new)

    def test_unknown_channel_fails_closed(self):
        with self.assertRaises(mod.HostapdConfigError):
            mod.render_channel("interface=ap0\nchannel=6\n", None)

    def test_non_techworld_interface_rejected(self):
        with self.assertRaises(mod.HostapdConfigError):
            mod.render_channel("interface=wlan0\nchannel=6\n", 11)

if __name__ == "__main__":
    unittest.main()
