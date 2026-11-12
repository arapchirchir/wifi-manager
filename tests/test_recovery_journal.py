"""Durable journal tests use only disposable directories; no system services."""
from pathlib import Path
import json
import os
import tempfile
import unittest

from installer.recovery_journal import (
    NAME, JournalError, begin_journal, read_journal, mark_journal,
)


class JournalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name) / "private"
        self.folder.mkdir(mode=0o700)

    def test_intent_and_success_remain_for_review(self):
        begin_journal(self.folder, 11)
        self.assertEqual(read_journal(self.folder)["state"], "pending")
        result = mark_journal(self.folder, "active_needs_review")
        self.assertEqual(result["state"], "active_needs_review")
        self.assertEqual(read_journal(self.folder), result)
        self.assertEqual(os.stat(self.folder / NAME).st_mode & 0o777, 0o600)

    def test_failed_review_state_persists(self):
        begin_journal(self.folder, 6)
        mark_journal(self.folder, "failed_needs_review")
        self.assertEqual(read_journal(self.folder)["channel"], 6)
        self.assertEqual(read_journal(self.folder)["state"], "failed_needs_review")

    def test_existing_marker_blocks_even_if_complete(self):
        begin_journal(self.folder, 11)
        mark_journal(self.folder, "failed_needs_review")
        with self.assertRaisesRegex(JournalError, "operator review"):
            begin_journal(self.folder, 11)

    def test_pending_marker_blocks_crash_restart(self):
        begin_journal(self.folder, 11)
        with self.assertRaises(JournalError):
            begin_journal(self.folder, 11)

    def test_symlink_marker_is_refused(self):
        target = self.folder / "other.json"
        target.write_text("{}")
        (self.folder / NAME).symlink_to(target)
        with self.assertRaises(JournalError):
            begin_journal(self.folder, 11)
        with self.assertRaises(OSError):
            read_journal(self.folder)

    def test_permissive_directory_is_refused(self):
        self.folder.chmod(0o755)
        with self.assertRaises(JournalError):
            begin_journal(self.folder, 11)

    def test_malformed_journal_is_not_adopted(self):
        (self.folder / NAME).write_text("not json")
        with self.assertRaises(JournalError):
            read_journal(self.folder)

    def test_world_readable_journal_is_rejected(self):
        begin_journal(self.folder, 11)
        (self.folder / NAME).chmod(0o644)
        with self.assertRaises(JournalError):
            mark_journal(self.folder, "active_needs_review")

    def test_channel_validation_rejects_unsupported(self):
        for channel in (0, 12, True, "11"):
            with self.subTest(channel=channel):
                with self.assertRaises(JournalError):
                    begin_journal(self.folder, channel)
        self.assertIsNone(read_journal(self.folder))

    def test_terminal_state_cannot_be_overwritten(self):
        begin_journal(self.folder, 11)
        mark_journal(self.folder, "active_needs_review")
        with self.assertRaises(JournalError):
            mark_journal(self.folder, "failed_needs_review")

    def test_missing_marker_has_no_state(self):
        self.assertIsNone(read_journal(self.folder))


if __name__ == "__main__":
    unittest.main()
