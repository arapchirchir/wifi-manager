"""Offline tests for read-only upstream health probe."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "techworld-upstream-health.py"
spec = importlib.util.spec_from_file_location("techworld_upstream_health", SOURCE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class FakeRunner:
    def __init__(self, connected=True, channel=11, ssid="Talai", gateway=True):
        self.connected = connected
        self.channel = channel
        self.ssid = ssid
        self.gateway = gateway
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "nmcli":
            return "100 (connected)\n" if self.connected else "30 (disconnected)\n"
        if cmd[0] == "iw":
            return ("Interface wlp109s0\n" +
                    (f"\tssid {self.ssid}\n" if self.ssid else "") +
                    (f"\tchannel {self.channel} (2462 MHz)\n"
                     if self.channel is not None else ""))
        if cmd[0] == "ip":
            return json.dumps(
                [{"dst": "default", "gateway": "192.168.100.1", "dev": "wlp109s0"}]
                if self.gateway else []
            )
        raise AssertionError(f"Unexpected command: {cmd}")


class UpstreamHealthTests(unittest.TestCase):
    def test_connected_upstream_healthy(self):
        runner = FakeRunner()
        report = mod.inspect("wlp109s0", 11, runner)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["default_gateway"], "192.168.100.1")
        self.assertEqual({c[0] for c in runner.calls}, {"nmcli", "iw", "ip"})

    def test_disconnected_fails(self):
        self.assertFalse(mod.inspect("wlp109s0", 11, FakeRunner(connected=False))["healthy"])

    def test_changed_channel_fails(self):
        report = mod.inspect("wlp109s0", 6, FakeRunner(channel=11))
        self.assertFalse(report["healthy"])
        self.assertTrue(any("changed" in error for error in report["errors"]))

    def test_missing_default_gateway_fails(self):
        self.assertFalse(mod.inspect("wlp109s0", 11, FakeRunner(gateway=False))["healthy"])

    def test_missing_association_fails(self):
        self.assertFalse(mod.inspect("wlp109s0", 11, FakeRunner(ssid=None))["healthy"])

    def test_invalid_interface_fails_before_commands(self):
        runner = FakeRunner()
        with self.assertRaises(mod.HealthError):
            mod.inspect("--bad", 11, runner)
        self.assertEqual(runner.calls, [])

    def test_inspection_failure_fails_closed(self):
        def fail(_cmd):
            raise mod.HealthError("command failed")
        report = mod.inspect("wlp109s0", 11, fail)
        self.assertFalse(report["healthy"])
        self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
