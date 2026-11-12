"""Static safety audit tests, no service or interface changes."""
from pathlib import Path
import unittest

from installer.deployment_audit import audit_repository, audit_sources


class AuditTests(unittest.TestCase):
    def test_repo_reports_unsafe_legacy_cleanup(self):
        root = Path(__file__).resolve().parents[1]
        result = audit_repository(root)
        self.assertFalse(result["deployment_safe"])
        self.assertTrue(any(f["reason"] == "name-only AP deletion"
                            for f in result["findings"]))
        self.assertTrue(any("bridge deletion" in f["reason"]
                            for f in result["findings"]))

    def test_clean_illustrative_source_not_declared_deployable(self):
        result = audit_sources({"test": "echo verified"})
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["deployment_safe"])

    def test_execstop_name_only_is_flagged(self):
        result = audit_sources({"ap.service": "ExecStop=/bin/sh -c 'iw dev ap0 del'"})
        self.assertTrue(any("systemd" in x["reason"] for x in result["findings"]))


if __name__ == "__main__":
    unittest.main()
