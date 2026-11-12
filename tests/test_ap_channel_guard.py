"""Offline regression tests for AP channel guard. No live network actions."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "techworld-ap-prepare"

class GuardTests(unittest.TestCase):
    def run_guard(self, upstream, ap_channel, associated=True):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            iw = root / "iw"
            ip = root / "ip"
            cfg = root / "hostapd.conf"
            cfg.write_text(f"interface=ap0\nssid=Techworld-WiFi\nchannel={ap_channel}\n")
            iw.write_text("#!/bin/sh\n"
                          "echo 'Interface wlp109s0'\n" +
                          ("echo 'ssid Talai'\n" if associated else "") +
                          f"echo 'channel {upstream} (2462 MHz)'\n")
            ip.write_text("#!/bin/sh\necho 'MOCK IP CALLED' >&2\nexit 99\n")
            iw.chmod(0o755)
            ip.chmod(0o755)
            env = dict(os.environ)
            env["PATH"] = str(root) + ":" + env.get("PATH", "")
            env["TECHWORLD_HOSTAPD_CONF"] = str(cfg)
            return subprocess.run(["bash", str(SCRIPT)], env=env,
                                  text=True, capture_output=True, timeout=8, check=False)

    def test_mismatch_does_not_touch_interface(self):
        p = self.run_guard(11, 6)
        self.assertEqual(p.returncode, 1)
        self.assertIn("channel is 11", p.stderr)
        self.assertNotIn("MOCK IP CALLED", p.stderr)

    def test_absent_association_does_not_touch_interface(self):
        p = self.run_guard(11, 11, associated=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("not associated", p.stderr)

    def test_valid_channel_eleven_passes_guard(self):
        p = self.run_guard(11, 11)
        self.assertEqual(p.returncode, 99)
        self.assertIn("MOCK IP CALLED", p.stderr)

    def test_non_numeric_channel_is_rejected(self):
        p = self.run_guard("unknown", "unknown")
        self.assertEqual(p.returncode, 1)

if __name__ == "__main__":
    unittest.main()
