"""Offline post-start health checks with all commands simulated."""
import importlib.util
import json
import unittest
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / "scripts" / "techworld-post-start-health.py"
spec = importlib.util.spec_from_file_location("techworld_post_start_health", FILE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeRunner:
    def __init__(self, *, connected=True, uplink_channel=11,
                 ap_channel=11, ap_type="AP", inactive=None, ap_exists=True):
        self.connected = connected
        self.uplink_channel = uplink_channel
        self.ap_channel = ap_channel
        self.ap_type = ap_type
        self.inactive = inactive
        self.ap_exists = ap_exists
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "nmcli":
            return "100 (connected)\n" if self.connected else "30 (disconnected)\n"
        if cmd[0] == "ip":
            return json.dumps([{"dst": "default", "gateway": "192.168.100.1",
                                "dev": "wlp109s0"}])
        if cmd[0] == "systemctl":
            return "inactive\n" if cmd[-1] == self.inactive else "active\n"
        if cmd[0] == "iw":
            if cmd[-1] == "link":
                return "Connected to 04:25:c5:9a:77:a0 (on wlp109s0)\n\tSSID: Talai\n"
            if cmd[2] == "ap0":
                if not self.ap_exists:
                    raise module.upstream.HealthError("No such interface")
                return f"Interface ap0\n\ttype {self.ap_type}\n\tchannel {self.ap_channel} (2462 MHz)\n"
            return f"Interface wlp109s0\n\tssid Talai\n\ttype managed\n\tchannel {self.uplink_channel} (2462 MHz)\n"
        raise AssertionError(f"Unexpected command {cmd}")


class PostStartHealthTests(unittest.TestCase):
    def test_healthy_upstream_and_hotspot(self):
        runner = FakeRunner()
        report = module.inspect("wlp109s0", runner=runner)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["upstream"]["default_gateway"], "192.168.100.1")
        self.assertEqual(report["ap"]["channel"], 11)
        self.assertEqual(len(report["services"]), 5)

    def test_disconnected_upstream(self):
        report = module.inspect("wlp109s0", runner=FakeRunner(connected=False))
        self.assertFalse(report["healthy"])

    def test_channel_mismatch(self):
        report = module.inspect("wlp109s0", runner=FakeRunner(ap_channel=6))
        self.assertFalse(report["healthy"])
        self.assertTrue(any("channel" in err for err in report["errors"]))

    def test_inactive_child_service(self):
        report = module.inspect("wlp109s0", runner=FakeRunner(inactive="opennds"))
        self.assertFalse(report["healthy"])

    def test_missing_ap_interface(self):
        report = module.inspect("wlp109s0", runner=FakeRunner(ap_exists=False))
        self.assertFalse(report["healthy"])

    def test_wrong_ap_mode(self):
        report = module.inspect("wlp109s0", runner=FakeRunner(ap_type="managed"))
        self.assertFalse(report["healthy"])

    def test_invalid_ap_interface_does_not_run_commands(self):
        runner = FakeRunner()
        report = module.inspect("wlp109s0", ap="--bad", runner=runner)
        self.assertFalse(report["healthy"])
        self.assertEqual(runner.calls, [])

    def test_never_changes_network_or_services(self):
        runner = FakeRunner()
        module.inspect("wlp109s0", runner=runner)
        self.assertEqual({cmd[0] for cmd in runner.calls}, {"nmcli", "ip", "systemctl", "iw"})
        self.assertTrue(all("restart" not in cmd and "stop" not in cmd and "up" not in cmd
                            for cmd in runner.calls))


if __name__ == "__main__":
    unittest.main()
