"""Private per-interface intent tests; no live interface operations."""
import json
import os
from pathlib import Path
import tempfile
import unittest

from installer.creation_intent import (
    IntentError, record_intent, read_intent, inspect_intents,
)


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name) / "private"
        self.dir.mkdir(mode=0o700)

    def test_durable_intent_survives_read(self):
        record_intent(self.dir, "ap0", "ap")
        self.assertEqual(read_intent(self.dir, "ap0", "ap"),
                         {"version": 1, "name": "ap0", "kind": "ap"})
        self.assertEqual((self.dir / "ap0.intent.json").stat().st_mode & 0o777, 0o600)

    def test_missing_intent_has_no_evidence(self):
        self.assertIsNone(read_intent(self.dir, "ap0", "ap"))

    def test_existing_intent_blocks_recreation(self):
        record_intent(self.dir, "ap0", "ap")
        with self.assertRaisesRegex(IntentError, "requires review"):
            record_intent(self.dir, "ap0", "ap")

    def test_symlink_intent_blocks_and_is_not_followed(self):
        target = self.dir / "other"
        target.write_text("secret")
        (self.dir / "ap0.intent.json").symlink_to(target)
        with self.assertRaises(IntentError):
            record_intent(self.dir, "ap0", "ap")
        with self.assertRaises(OSError):
            read_intent(self.dir, "ap0", "ap")
        self.assertEqual(target.read_text(), "secret")

    def test_insecure_directory_blocks(self):
        self.dir.chmod(0o755)
        with self.assertRaises(IntentError):
            record_intent(self.dir, "ap0", "ap")

    def test_unknown_or_mismatched_kind_rejected(self):
        for name, kind in (("wlp109s0", "ap"), ("ap0", "bridge"),
                           ("br-techworld", "ap"), ("ap0", "AP")):
            with self.subTest(name=name, kind=kind):
                with self.assertRaises(IntentError):
                    record_intent(self.dir, name, kind)

    def test_bad_content_never_authorizes_ownership(self):
        path = record_intent(self.dir, "ap0", "ap")
        path.write_text(json.dumps({"version": 1, "name": "ap0",
                                    "kind": "bridge"}))
        with self.assertRaises(IntentError):
            read_intent(self.dir, "ap0", "ap")

    def test_permissive_file_rejected(self):
        path = record_intent(self.dir, "ap0", "ap")
        path.chmod(0o644)
        with self.assertRaises(IntentError):
            read_intent(self.dir, "ap0", "ap")

    def test_readonly_inspection_never_authorizes_cleanup(self):
        record_intent(self.dir, "br-techworld", "bridge")
        report = inspect_intents(self.dir)
        self.assertTrue(report["manual_review_required"])
        self.assertFalse(report["safe_to_restart"])
        self.assertFalse(report["automatic_cleanup_allowed"])
        self.assertEqual(set(report["intents"]), {"br-techworld"})


if __name__ == "__main__":
    unittest.main()
