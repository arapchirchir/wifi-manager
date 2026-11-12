"""Durable, fail-closed recovery marker for future supervised Techworld setup.

Records intent BEFORE any network mutation. An existing marker blocks every
new setup, including after a reported success, until a separate operator
review workflow exists. It does NOT authorize automatic deletion or recovery.
Only use while holding setup_lock() in a private, owner-only directory.
"""
import json
import os
from pathlib import Path
import stat
import tempfile

NAME = "startup-journal.json"
STATES = ("pending", "active_needs_review", "failed_needs_review")


class JournalError(RuntimeError):
    pass


def _directory(path):
    directory = Path(path)
    metadata = directory.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise JournalError("Journal directory must be a private owned directory")
    return directory


def _validate(record):
    if not isinstance(record, dict) or set(record) != {"version", "state", "channel"}:
        raise JournalError("Invalid recovery journal schema")
    if type(record["version"]) is not int or record["version"] != 1:
        raise JournalError("Unsupported recovery journal version")
    if record["state"] not in STATES:
        raise JournalError("Invalid recovery journal state")
    if type(record["channel"]) is not int or not 1 <= record["channel"] <= 11:
        raise JournalError("Invalid recovery journal channel")
    return record


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid()
                or metadata.st_mode & 0o077 or metadata.st_nlink != 1
                or metadata.st_size > 4096):
            raise JournalError("Unsafe journal file")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            try:
                record = json.load(stream)
            except (ValueError, UnicodeError) as exc:
                raise JournalError("Malformed recovery journal") from exc
        return _validate(record), metadata
    finally:
        if fd >= 0:
            os.close(fd)


def read_journal(directory):
    """Read an existing marker, or None when absent (never follow symlinks)."""
    path = _directory(directory) / NAME
    try:
        return _read(path)[0]
    except FileNotFoundError:
        return None


def _sync_dir(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _serialize(record):
    _validate(record)
    return (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")


def begin_journal(directory, channel):
    """Exclusively persist intent BEFORE touching a config/interface/service."""
    directory = _directory(directory)
    path = directory / NAME
    record = {"version": 1, "state": "pending", "channel": channel}
    payload = _serialize(record)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError as exc:
        raise JournalError("Existing recovery marker requires operator review") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _sync_dir(directory)
    except Exception:
        # Retain an uncertain journal on failure. Never silently remove it.
        raise
    return record


def mark_journal(directory, state):
    """Atomically replace an owned marker, never clear it automatically."""
    if state not in STATES[1:]:
        raise JournalError("Only terminal review-required states are allowed")
    directory = _directory(directory)
    path = directory / NAME
    old, metadata = _read(path)
    if old["state"] != "pending":
        raise JournalError("Journal is already terminal; operator review required")
    updated = {**old, "state": state}
    fd, temporary = tempfile.mkstemp(prefix=".journal-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(_serialize(updated))
            stream.flush()
            os.fsync(stream.fileno())
        latest, current = _read(path)
        if latest != old or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise JournalError("Recovery marker changed; refusing overwrite")
        os.replace(temporary, path)
        _sync_dir(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return updated
