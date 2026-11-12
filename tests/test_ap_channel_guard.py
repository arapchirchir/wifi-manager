"""Offline regression tests for AP channel guard. No live network actions."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "techworld-ap-prepare"

class GuardTests(unittest.TestCase):
    def run_guard(self, upstream, ap_channel, associated=True, connected=True, default_route=True, existing_interface=None):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            iw = root / "iw"
            ip = root / "ip"
            nmcli = root / "nmcli"
            cfg = root / "hostapd.conf"
            cfg.write_text(f"interface=ap0\nssid=Techworld-WiFi\nhw_mode=g\nchannel={ap_channel}\n")
            iw.write_text(
                "#!/bin/sh\n"
                "if [ \"$3\" = link ]; then\n"
                + ("  echo 'Connected to 04:25:c5:9a:77:a0 (on wlp109s0)'\n"
                   "  echo 'SSID: Talai_B'\n" if associated else "  echo 'Not connected.'\n")
                + "else\n  echo 'Interface wlp109s0'\n"
                + f"  echo 'channel {upstream} (2462 MHz)'\n"
                + "fi\n"
            )
            nmcli.write_text(
                "#!/bin/sh\n"
                + ("echo '100 (connected)'\n" if connected else "echo '30 (disconnected)'\n")
            )
            ip.write_text(
                "#!/bin/sh\n"
                + (f'if [ "$1 $2 $3" = "link show {existing_interface}" ]; then exit 0; fi\n'
                   if existing_interface else "")
                + 'if [ "$1 $2 $3 $4 $5 $6" = "-4 route show default dev wlp109s0" ]; then\n'
                + ("  echo 'default via 192.168.100.1 dev wlp109s0'\n" if default_route else "  :\n")
                + "  exit 0\nfi\necho 'MOCK IP CALLED' >&2\nexit 99\n"
            )
            nmcli.chmod(0o755)
            iw.chmod(0o755)
            ip.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = str(root) + ":" + env.get("PATH", "")
            env["TECHWORLD_HOSTAPD_CONF"] = str(cfg)
            proc = subprocess.run(["bash", str(SCRIPT)], env=env,
                                  text=True, capture_output=True, timeout=8, check=False)
            return proc, cfg.read_text(), (root / "hostapd.conf.before-channel-sync").exists()

    def test_channel_syncs_before_interface_setup(self):
        p, config, backed_up = self.run_guard(11, 6)
        self.assertEqual(p.returncode, 99)
        self.assertIn("MOCK IP CALLED", p.stderr)
        self.assertIn("channel=11", config)
        self.assertTrue(backed_up)

    def test_absent_association_does_not_touch_interface(self):
        p, config, backed_up = self.run_guard(11, 11, associated=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("No active upstream Wi-Fi association", p.stderr)

    def test_valid_channel_eleven_passes_guard(self):
        p, config, backed_up = self.run_guard(11, 11)
        self.assertFalse(backed_up)
        self.assertEqual(p.returncode, 99)
        self.assertIn("MOCK IP CALLED", p.stderr)

    def test_unhandled_channel_fails_before_touching_interface(self):
        p, config, backed_up = self.run_guard(36, 6)
        self.assertEqual(p.returncode, 1)
        self.assertIn("channel=6", config)
        self.assertFalse(backed_up)
        self.assertNotIn("MOCK IP CALLED", p.stderr)

    def test_disconnected_upstream_rejected_before_interfaces(self):
        p, cfg, backed_up = self.run_guard(11, 6, connected=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not connected", p.stderr)
        self.assertIn("channel=6", cfg)
        self.assertFalse(backed_up)

    def test_no_default_route_rejected_before_interfaces(self):
        p, cfg, backed_up = self.run_guard(11, 6, default_route=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("No IPv4 default route", p.stderr)
        self.assertIn("channel=6", cfg)
        self.assertFalse(backed_up)

    def test_existing_ap_is_not_adopted(self):
        p, cfg, backup = self.run_guard(11, 6, existing_interface="ap0")
        self.assertEqual(p.returncode, 1)
        self.assertIn("refusing to adopt", p.stderr)
        self.assertIn("channel=6", cfg)
        self.assertFalse(backup)

    def test_existing_bridge_is_not_adopted(self):
        p, cfg, backup = self.run_guard(11, 6, existing_interface="br-techworld")
        self.assertEqual(p.returncode, 1)
        self.assertIn("refusing to adopt", p.stderr)
        self.assertIn("channel=6", cfg)
        self.assertFalse(backup)

    def test_non_numeric_channel_is_rejected(self):
        p, config, backed_up = self.run_guard("unknown", "unknown")
        self.assertEqual(p.returncode, 1)

if __name__ == "__main__":
    unittest.main()
