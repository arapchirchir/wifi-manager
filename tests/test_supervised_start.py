"""Offline supervisor simulations. Never issue real systemd or Wi-Fi commands."""
import importlib.util
import json
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "scripts" / "techworld-supervised-start.py"
spec = importlib.util.spec_from_file_location("techworld_supervised_start", SRC)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class SimulatedSystem:
    def __init__(self, connected=True, service_state="inactive",
                 start_fails=False, stop_fails=False):
        self.connected = connected
        self.service_state = service_state
        self.start_fails = start_fails
        self.stop_fails = stop_fails
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        if cmd[0] == "nmcli":
            return "100 (connected)\n" if self.connected else "30 (disconnected)\n"
        if cmd[0] == "iw":
            if cmd[-1] == "link":
                return "Connected to 04:25:c5:9a:77:a0 (on wlp109s0)\n\tSSID: Talai\n"
            return "Interface wlp109s0\nssid Talai\nchannel 11 (2462 MHz)\n"
        if cmd[0] == "ip":
            return json.dumps([{
                "dst": "default", "dev": "wlp109s0",
                "gateway": "192.168.100.1",
            }])
        if cmd[:2] == ["systemctl", "show"]:
            return self.service_state + "\n"
        if cmd[:2] == ["systemctl", "start"]:
            if self.start_fails:
                raise mod.upstream.HealthError("simulated start failure")
            self.service_state = "active"
            return ""
        if cmd[:2] == ["systemctl", "stop"]:
            if self.stop_fails:
                raise mod.upstream.HealthError("simulated stop failure")
            self.service_state = "inactive"
            return ""
        raise AssertionError(f"Unexpected command: {cmd}")

    def mutations(self):
        return [c for c in self.calls if c[0] == "systemctl" and c[1] in ("start", "stop")]


class SupervisorTests(unittest.TestCase):
    def test_preview_is_read_only(self):
        system = SimulatedSystem()
        report = mod.supervise("wlp109s0", runner=system)
        self.assertEqual(report["mode"], "preview")
        self.assertFalse(report["errors"])
        self.assertEqual(system.mutations(), [])

    def test_healthy_start_with_explicit_consent(self):
        system = SimulatedSystem()
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, post_probe=lambda _: {"healthy": True},
            root_check=lambda: 0
        )
        self.assertTrue(report["started"])
        self.assertFalse(report["recovery_attempted"])
        self.assertEqual(system.mutations(), [
            ["systemctl", "start", "techworld-hotspot"]
        ])

    def test_failed_post_start_stops_own_hotspot(self):
        system = SimulatedSystem()
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, post_probe=lambda _: {"healthy": False},
            root_check=lambda: 0, attempts=2,
        )
        self.assertFalse(report["started"])
        self.assertTrue(report["recovery_attempted"])
        self.assertEqual(system.mutations(), [
            ["systemctl", "start", "techworld-hotspot"],
            ["systemctl", "stop", "techworld-hotspot"],
        ])

    def test_partial_start_failure_attempts_stop(self):
        system = SimulatedSystem(start_fails=True)
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, root_check=lambda: 0,
        )
        self.assertFalse(report["started"])
        self.assertTrue(report["recovery_attempted"])
        self.assertEqual(system.mutations()[-1],
                         ["systemctl", "stop", "techworld-hotspot"])

    def test_existing_active_hotspot_is_never_stopped(self):
        system = SimulatedSystem(service_state="active")
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, root_check=lambda: 0,
        )
        self.assertFalse(report["started"])
        self.assertEqual(system.mutations(), [])

    def test_no_consent_does_not_start(self):
        system = SimulatedSystem()
        report = mod.supervise("wlp109s0", execute=True, runner=system,
                               root_check=lambda: 0)
        self.assertTrue(report["errors"])
        self.assertEqual(system.mutations(), [])

    def test_not_root_does_not_start(self):
        system = SimulatedSystem()
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, root_check=lambda: 1000
        )
        self.assertTrue(report["errors"])
        self.assertEqual(system.mutations(), [])

    def test_disconnected_upstream_does_not_start(self):
        system = SimulatedSystem(connected=False)
        report = mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, root_check=lambda: 0
        )
        self.assertFalse(report["started"])
        self.assertEqual(system.mutations(), [])

    def test_only_hotspot_service_can_be_mutated(self):
        system = SimulatedSystem()
        mod.supervise(
            "wlp109s0", execute=True, consent=mod.CONSENT,
            runner=system, root_check=lambda: 0,
            post_probe=lambda _: {"healthy": False},
        )
        self.assertTrue(all(
            c[-1] == "techworld-hotspot" for c in system.mutations()
        ))


if __name__ == "__main__":
    unittest.main()
