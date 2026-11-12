"""Offline checks; never query or modify the host networking stack."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "techworld-preflight.py"
spec = importlib.util.spec_from_file_location("techworld_preflight", SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class FakeHost:
    def __init__(self, installed=(), interfaces=(), port=False):
        self.installed = set(installed)
        self.interfaces = set(interfaces)
        self.port = port
        self.calls = []

    def __call__(self, command):
        self.calls.append(tuple(command))
        if command[0] == "systemctl":
            name = command[3]
            found = name in self.installed
            output = (f"LoadState={'loaded' if found else 'not-found'}\n"
                      f"ActiveState={'active' if found else 'inactive'}\n"
                      f"FragmentPath={'/etc/systemd/system/' + name if found else ''}\n")
            return subprocess.CompletedProcess(command, 0, output, "")
        if command[0] == "ip":
            return subprocess.CompletedProcess(command, 0 if command[-1] in self.interfaces else 1,
                                               "[]" if command[-1] in self.interfaces else "",
                                               "" if command[-1] in self.interfaces else "Device does not exist")
        if command[0] == "ss":
            return subprocess.CompletedProcess(command, 0, "LISTEN ... :2050\n" if self.port else "", "")
        raise AssertionError(f"Unexpected command {command}")


class PreflightTests(unittest.TestCase):
    def check_host(self, fake, manifest=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "install-manifest.json"
            if manifest is not None:
                path.write_text(json.dumps(manifest))
            return preflight.inspect(manifest_path=path, runner=fake)

    def test_clean_machine_with_shared_dnsmasq(self):
        fake = FakeHost(installed={"dnsmasq.service", "NetworkManager.service"})
        report = self.check_host(fake)
        self.assertEqual(report["status"], "clean")
        self.assertFalse(report["requires_explicit_confirmation"])
        self.assertEqual(report["actions_performed"], [])

    def test_existing_unrecorded_installation_requires_adoption(self):
        fake = FakeHost(installed={"techworld-hotspot.service", "opennds.service"},
                        interfaces={"ap0", "br-techworld"}, port=True)
        report = self.check_host(fake)
        self.assertEqual(report["status"], "adoption_required")
        self.assertTrue(report["requires_explicit_confirmation"])
        self.assertEqual(report["exit_code_strict"], 20)

    def test_recorded_installation_is_not_auto_removed(self):
        fake = FakeHost(installed={"techworld-hotspot.service", "opennds.service"}, port=True)
        manifest = {"schema_version": 1, "owner": "techworld-wifi",
                    "units": ["techworld-hotspot.service", "opennds.service"]}
        report = self.check_host(fake, manifest)
        self.assertEqual(report["status"], "recorded_existing")
        self.assertEqual(report["actions_performed"], [])

    def test_foreign_opennds_must_not_be_replaced(self):
        report = self.check_host(FakeHost(installed={"opennds.service"}, port=True))
        self.assertEqual(report["status"], "conflict")

    def test_reserved_interface_conflict(self):
        report = self.check_host(FakeHost(interfaces={"ap0"}))
        self.assertEqual(report["status"], "conflict")

    def test_listener_conflict(self):
        report = self.check_host(FakeHost(port=True))
        self.assertEqual(report["status"], "conflict")

    def test_broken_manifest_fails_closed(self):
        report = self.check_host(FakeHost(), {"owner": "someone-else", "units": []})
        self.assertEqual(report["status"], "inspection_failed")

    def test_invalid_interface_name_rejected(self):
        self.assertFalse(preflight.valid_ifname("--bad"))
        self.assertFalse(preflight.valid_ifname("too-long-for-linux-interface"))
        self.assertTrue(preflight.valid_ifname("ap0"))

    def test_no_destructive_commands(self):
        fake = FakeHost(installed={"techworld-hotspot.service", "opennds.service"})
        self.check_host(fake)
        self.assertEqual({c[0] for c in fake.calls}, {"systemctl", "ip", "ss"})
        self.assertTrue(all("stop" not in c and "disable" not in c for c in fake.calls))


if __name__ == "__main__":
    unittest.main()
