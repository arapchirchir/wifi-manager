"""Offline tests for consented updates; never touch host services or files."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "installer" / "apply_existing.py"
spec = importlib.util.spec_from_file_location("techworld_apply", MODULE)
apply = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apply)

HOSTAPD_CONF = """interface=ap0
driver=nl80211
ssid=Techworld-WiFi
hw_mode=g
channel=6
"""
DNSMASQ_CONF = """interface=br-techworld
bind-interfaces
dhcp-range=10.77.77.50,10.77.77.200,255.255.255.0,12h
"""
PLAN = {
    "preflight_status": "adoption_required",
    "wireless": {
        "ssid": "Wireless", "channel": 6, "ap_interface": "ap0",
        "bridge": "br-techworld",
    },
    "portal": {
        "domain": "wireless.test", "gateway": "10.77.77.1/24",
        "dhcp_start": "10.77.77.50", "dhcp_end": "10.77.77.200",
    },
}


class FakeRunner:
    def __init__(self, restart_failure=None):
        self.calls = []
        self.restart_failure = restart_failure

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["systemctl", "is-active"]:
            return "active\n"
        if args[:2] == ["systemctl", "restart"]:
            if self.restart_failure == args[-1]:
                self.restart_failure = None
                raise apply.ApplyError("Simulated service restart failure")
            return ""
        if args[:4] == ["ip", "-j", "-4", "address"]:
            return json.dumps([
                {"ifname": "br-techworld", "addr_info": [
                    {"family": "inet", "local": "10.77.77.1", "prefixlen": 24}
                ]}
            ])
        if args[0] == "dnsmasq" and "--test" in args:
            return ""
        raise AssertionError(f"Unexpected command: {args}")


class ApplyExistingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.hostapd = root / "hostapd.conf"
        self.dnsmasq = root / "dnsmasq.conf"
        self.hostapd_service = root / "techworld-hostapd.service"
        self.dnsmasq_service = root / "techworld-dhcp.service"
        self.backups = root / "backups"
        self.hostapd.write_text(HOSTAPD_CONF)
        self.dnsmasq.write_text(DNSMASQ_CONF)
        self.hostapd_service.write_text("ExecStart=/usr/sbin/hostapd " + str(self.hostapd))
        self.dnsmasq_service.write_text("ExecStart=/usr/sbin/dnsmasq --conf-file=" + str(self.dnsmasq))
        patches = [
            patch.object(apply, "HOSTAPD", self.hostapd),
            patch.object(apply, "DNSMASQ", self.dnsmasq),
            patch.object(apply, "HOSTAPD_UNIT", self.hostapd_service),
            patch.object(apply, "DNSMASQ_UNIT", self.dnsmasq_service),
            patch.object(apply, "BACKUPS", self.backups),
            patch.object(apply.os, "geteuid", return_value=0),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_ssid_change_changes_only_exact_ssid(self):
        updated = apply.updated_ssid(HOSTAPD_CONF, "Wireless", 6)
        self.assertIn("ssid=Wireless\n", updated)
        self.assertIn("channel=6\n", updated)
        self.assertNotIn("ssid=Techworld-WiFi\n", updated)

    def test_wifi_channel_mismatch_is_rejected(self):
        with self.assertRaises(apply.ApplyError):
            apply.updated_ssid(HOSTAPD_CONF, "Wireless", 11)

    def test_dns_alias_generated_once(self):
        updated = apply.updated_dns(DNSMASQ_CONF, "wireless.test", "10.77.77.1")
        self.assertIn("host-record=wireless.test,10.77.77.1", updated)
        self.assertEqual(
            apply.updated_dns(updated, "wireless.test", "10.77.77.1"), updated
        )

    def test_existing_conflicting_dns_record_rejected(self):
        with self.assertRaises(apply.ApplyError):
            apply.updated_dns(
                DNSMASQ_CONF + "\nhost-record=wireless.test,10.99.99.1\n",
                "wireless.test", "10.77.77.1",
            )

    def test_updates_with_backup_and_restarts_only_two_children(self):
        runner = FakeRunner()
        result = apply.apply_existing(PLAN, runner)
        self.assertTrue(result["changed"])
        self.assertIn("ssid=Wireless", self.hostapd.read_text())
        self.assertIn("host-record=wireless.test,10.77.77.1", self.dnsmasq.read_text())
        backup = Path(result["backup_directory"])
        self.assertEqual((backup / "hostapd.conf").read_text(), HOSTAPD_CONF)
        self.assertEqual((backup / "dnsmasq.conf").read_text(), DNSMASQ_CONF)
        restarts = [x[-1] for x in runner.calls if x[:2] == ["systemctl", "restart"]]
        self.assertEqual(restarts, ["techworld-hostapd", "techworld-dhcp"])

    def test_failure_restores_exact_configuration(self):
        runner = FakeRunner(restart_failure="techworld-dhcp")
        with self.assertRaises(apply.ApplyError):
            apply.apply_existing(PLAN, runner)
        self.assertEqual(self.hostapd.read_text(), HOSTAPD_CONF)
        self.assertEqual(self.dnsmasq.read_text(), DNSMASQ_CONF)

    def test_unchanged_settings_do_not_restart(self):
        self.hostapd.write_text(HOSTAPD_CONF.replace(
            "Techworld-WiFi", "Wireless"
        ))
        self.dnsmasq.write_text(
            apply.updated_dns(DNSMASQ_CONF, "wireless.test", "10.77.77.1")
        )
        runner = FakeRunner()
        result = apply.apply_existing(PLAN, runner)
        self.assertFalse(result["changed"])
        self.assertFalse(any(c[:2] == ["systemctl", "restart"] for c in runner.calls))

    def test_different_gateway_is_rejected(self):
        plan = json.loads(json.dumps(PLAN))
        plan["portal"]["gateway"] = "10.77.78.1/24"
        with self.assertRaises(apply.ApplyError):
            apply.apply_existing(plan, FakeRunner())

    def test_dhcp_pool_change_is_rejected(self):
        plan = json.loads(json.dumps(PLAN))
        plan["portal"]["dhcp_start"] = "10.77.77.51"
        with self.assertRaises(apply.ApplyError):
            apply.apply_existing(plan, FakeRunner())

    def test_unprivileged_apply_is_rejected(self):
        with patch.object(apply.os, "geteuid", return_value=1000):
            with self.assertRaises(apply.ApplyError):
                apply.apply_existing(PLAN, FakeRunner())

    def test_clean_install_not_implemented(self):
        plan = json.loads(json.dumps(PLAN))
        plan["preflight_status"] = "clean"
        with self.assertRaises(apply.ApplyError):
            apply.apply_existing(plan, FakeRunner())


if __name__ == "__main__":
    unittest.main()
