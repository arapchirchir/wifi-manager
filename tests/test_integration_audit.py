"""Regression checks for read-only integration audit and source safety."""
import importlib.util
from pathlib import Path
import unittest

BASE = Path(__file__).resolve().parents[1]
SCRIPT = BASE / "scripts" / "techworld-integration-audit.py"
spec = importlib.util.spec_from_file_location("techworld_integration_audit", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class IntegrationAuditTests(unittest.TestCase):
    def test_audit_reads_existing_repo_sources_without_mutation(self):
        from installer.deployment_audit import audit_repository
        report = audit_repository(BASE)
        self.assertFalse(report["deployment_safe"])
        self.assertTrue(report["findings"])
        files = {item["path"] for item in report["findings"]}
        self.assertIn("systemd/techworld-ap.service", files)
        self.assertIn("scripts/techworld-ap-cleanup", files)

    def test_script_does_not_contain_live_system_calls(self):
        source = SCRIPT.read_text()
        self.assertNotIn("subprocess.run", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("ip link add", source)

    def test_adapters_have_no_default_mutator(self):
        from installer.linux_adapters import LinkInspectionAdapter, AdapterError
        adapter = LinkInspectionAdapter(lambda _command: "[]")
        for method in (adapter.create, adapter.remove):
            with self.assertRaises(AdapterError):
                method("ap0", "ap", 5)


if __name__ == "__main__":
    unittest.main()
