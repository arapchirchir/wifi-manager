"""Lock tests operate exclusively on temporary files and local file locks."""
from pathlib import Path
import tempfile
import unittest

from installer.setup_lock import setup_lock, LockError
from installer.startup_controller import startup, StartupError


class LockTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.folder = Path(t.name) / "private"
        self.folder.mkdir(mode=0o700)

    def test_lock_and_unlock(self):
        with setup_lock(self.folder):
            self.assertTrue((self.folder / ".startup.lock").exists())
        with setup_lock(self.folder):
            pass

    def test_second_attempt_is_refused(self):
        with setup_lock(self.folder):
            with self.assertRaisesRegex(LockError, "holds the lock"):
                with setup_lock(self.folder):
                    pass

    def test_permissive_directory_is_refused(self):
        self.folder.chmod(0o755)
        with self.assertRaisesRegex(LockError, "directory"):
            with setup_lock(self.folder):
                pass

    def test_symlinked_lock_is_refused(self):
        target = self.folder / "target"
        target.write_text("x")
        (self.folder / ".startup.lock").symlink_to(target)
        with self.assertRaises(OSError):
            with setup_lock(self.folder):
                pass

    def test_world_readable_lock_is_refused(self):
        lock = self.folder / ".startup.lock"
        lock.write_text("x")
        lock.chmod(0o644)
        with self.assertRaisesRegex(LockError, "permissions"):
            with setup_lock(self.folder):
                pass

    def test_setup_refused_if_lock_held_without_service_changes(self):
        class Services:
            def __init__(self):
                self.calls = []
            def state(self, unit):
                self.calls.append(unit)
                return "inactive"
            def start(self, unit):
                raise AssertionError("must not start")
            def stop(self, unit):
                raise AssertionError("must not stop")

        service = Services()
        with setup_lock(self.folder):
            with self.assertRaises(LockError):
                startup(None, service, receipt_dir=self.folder,
                        hostapd_path=self.folder / "hostapd.conf",
                        channel=11, upstream_check=lambda: ("Talai", 11),
                        post_check=lambda: True)
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()
