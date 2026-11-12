"""Private, non-blocking setup lock, intended for a future supervised installer.

The lock is retained across runs, never unlinked. It protects cooperating
processes only; it cannot serialize independently installed legacy scripts.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class LockError(RuntimeError):
    pass


@contextmanager
def setup_lock(directory):
    """Lock a private owner-only directory; reject symlinks and weak modes."""
    folder = Path(directory)
    meta = folder.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.geteuid() or meta.st_mode & 0o077:
        raise LockError("Setup lock directory must be private and owned")
    path = folder / ".startup.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LockError("Unsafe setup lock file")
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise LockError("Unsafe setup lock permissions")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LockError("Another Techworld setup transaction holds the lock") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
