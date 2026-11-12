"""Durable *intent*, not ownership, for reserved AP interface creation.

An intent is written and fsynced before adapter.create(). A crash between
the kernel operation and an ifindex receipt therefore leaves a review marker.
It can NEVER authorize deletion, adoption, or automated journal clearance.

Called only under setup_lock() in a pre-existing private directory.
"""
import json
import os
from pathlib import Path
import stat

RESERVED = {"ap0": "ap", "br-techworld": "bridge"}


class IntentError(RuntimeError):
    pass


def _directory(folder):
    path = Path(folder)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise IntentError("Interface intent directory must be private and owned")
    return path


def _path(folder, name, kind):
    if type(name) is not str or RESERVED.get(name) != kind:
        raise IntentError("Unrecognized interface intent")
    return _directory(folder) / (name + ".intent.json")


def _validate(value, name, kind):
    if (not isinstance(value, dict) or set(value) != {"version", "name", "kind"}
            or type(value["version"]) is not int or value["version"] != 1
            or value["name"] != name or value["kind"] != kind):
        raise IntentError("Invalid interface creation intent")
    return value


def record_intent(folder, name, kind):
    """Create exclusive 0600 marker and durably sync before any creation."""
    path = _path(folder, name, kind)
    payload = (json.dumps({"version": 1, "name": name, "kind": kind},
                          sort_keys=True) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
    except FileExistsError as exc:
        raise IntentError("Previous interface creation intent requires review") from exc
    with os.fdopen(fd, "wb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return path


def read_intent(folder, name, kind):
    """Return an existing safe intent, or None. Reject symlinks and tampering."""
    path = _path(folder, name, kind)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_nlink != 1
                or info.st_size > 4096):
            raise IntentError("Unsafe interface intent permissions or type")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            try:
                value = json.load(stream)
            except (ValueError, UnicodeError) as exc:
                raise IntentError("Malformed interface intent") from exc
        return _validate(value, name, kind)
    finally:
        if fd >= 0:
            os.close(fd)


def inspect_intents(folder):
    """Read-only summary; never permits restart or deletion."""
    found = {}
    for name, kind in RESERVED.items():
        data = read_intent(folder, name, kind)
        if data is not None:
            found[name] = data
    return {"intents": found, "safe_to_restart": False,
            "automatic_cleanup_allowed": False,
            "manual_review_required": bool(found)}
