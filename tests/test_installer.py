"""Unit tests for the installer configuration preview. No host changes."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

WIZARD = Path(__file__).resolve().parents[1] / "installer" / "wizard.py"
spec = importlib.util.spec_from_file_location("techworld_wizard", WIZARD)
wizard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wizard)

DEFAULTS = {
    "ssid": "Techworld-WiFi",
    "domain": "wireless.test",
    "uplink": "wlp109s0",
    "gateway": "10.77.77.1/24",
    "dhcp_start": "10.77.77.50",
    "dhcp_end": "10.77.77.200",
}


class WizardTests(unittest.TestCase):
    def test_valid_plan_changes_nothing(self):
        result = wizard.plan(DEFAULTS, {"status": "clean"})
        self.assertEqual(result["portal"]["domain"], "wireless.test")
        self.assertEqual(result["system_changes"], [])
        self.assertTrue(result["requires_explicit_approval_to_install"])

    def test_legacy_installation_needs_adoption(self):
        result = wizard.plan(DEFAULTS, {"status": "adoption_required"})
        self.assertEqual(result["preflight_status"], "adoption_required")
        self.assertIn("adoption", " ".join(result["warnings"]))

    def test_existing_recorded_install_needs_approval(self):
        result = wizard.plan(DEFAULTS, {"status": "recorded_existing"})
        self.assertTrue(result["requires_explicit_approval_to_install"])

    def test_conflict_blocks_plan(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.plan(DEFAULTS, {"status": "conflict"})

    def test_inspection_failure_blocks_plan(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.plan(DEFAULTS, {"status": "inspection_failed"})

    def test_wifi_ssid_utf8_length(self):
        self.assertEqual(wizard.validate_ssid("Pure Sip"), "Pure Sip")
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_ssid("é" * 17)

    def test_ssid_rejects_control_characters(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_ssid("wifi\nother")

    def test_local_domain_not_allowed(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_domain("wireless.local")

    def test_domain_normalization(self):
        self.assertEqual(wizard.validate_domain("Wireless.TEST."), "wireless.test")

    def test_invalid_domain_rejected(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_domain("wireless.invalid_domain")

    def test_upstream_cannot_use_ap(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_uplink("ap0")

    def test_gateway_must_be_private(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_network("8.8.8.1/24", "8.8.8.50", "8.8.8.200")

    def test_dhcp_range_cannot_include_gateway(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_network("10.77.77.1/24", "10.77.77.1", "10.77.77.200")

    def test_dhcp_range_must_fit_subnet(self):
        with self.assertRaises(wizard.ConfigurationError):
            wizard.validate_network("10.77.77.1/24", "10.77.77.50", "10.77.78.200")

    def test_wizard_auto_detected_defaults(self):
        detected = {
            "uplink": "wlan0", "channel": 11, "phy": "phy0",
            "gateway": "10.77.78.1/24",
            "dhcp_start": "10.77.78.50",
            "dhcp_end": "10.77.78.200",
            "source": "automatically selected unused private subnet",
            "occupied_networks": [],
            "preserve_existing": False,
        }
        with patch.object(wizard, "get_preflight", return_value={"status": "clean"}):
            with patch.object(wizard, "discover", return_value=detected):
                self.assertEqual(wizard.main(["--non-interactive"]), 0)

    def test_unknown_uplink_override_fails_closed(self):
        detected = {
            "uplink": "wlan0", "channel": 11, "phy": "phy0",
            "gateway": "10.77.78.1/24",
            "dhcp_start": "10.77.78.50",
            "dhcp_end": "10.77.78.200",
            "source": "automatically selected unused private subnet",
            "occupied_networks": [],
            "preserve_existing": False,
        }
        with patch.object(wizard, "get_preflight", return_value={"status": "clean"}):
            with patch.object(wizard, "discover", return_value=detected):
                self.assertEqual(
                    wizard.main(["--non-interactive", "--uplink", "doesnotexist"]), 2
                )


if __name__ == "__main__":
    unittest.main()
