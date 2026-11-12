"""Dedicated hostapd channel transaction for a supervised installer.

Does not alter system services or network interfaces. Caller is responsible
for taking an exclusive setup lock and for startup orchestration. The
configuration rollback compares the bytes we installed before restoring,
so third-party changes are never silently overwritten.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile


class ConfigError(RuntimeError):
    pass


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def render_channel(original, channel):
    """Validate and render legacy 2.4 GHz hostapd channel in memory."""
    if type(channel) is not int or not 1 <= channel <= 11:
        raise ConfigError("Legacy 2.4 GHz AP requires channel 1-11")
    try:
        text = original.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError("Invalid hostapd encoding") from exc
    fields = {}
    for key in ("interface", "hw_mode", "channel"):
        matches = re.findall(r"(?m)^" + key + r"=(.*)$", text)
        if len(matches) != 1:
            raise ConfigError(f"Expected exactly one {key} entry")
        fields[key] = matches[0]
    if fields["interface"] != "ap0" or fields["hw_mode"] != "g":
        raise ConfigError("Unsupported legacy AP configuration")
    if not fields["channel"].isdigit():
        raise ConfigError("Invalid existing channel")
    new = re.sub(r"(?m)^channel=\d+$", f"channel={channel}", text)
    return new.encode("utf-8")


def _read_regular(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ConfigError("Dedicated hostapd config must be a regular single-link file")
    return path.read_bytes(), info


def _replace_bytes(path, content, info):
    """Write fully then replace, keeping permissions and ownership."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=".techworld-hostapd-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def apply_channel(path, channel):
    """Replace dedicated hostapd config, returning a reversible transaction."""
    original, info = _read_regular(path)
    updated = render_channel(original, channel)
    if updated != original:
        # Caller has exclusive lock; avoid replacing a file changed in between.
        latest, latest_info = _read_regular(path)
        if latest != original or latest_info.st_ino != info.st_ino:
            raise ConfigError("Hostapd config changed during preparation")
        _replace_bytes(path, updated, info)
    return {"original": original, "installed_sha256": _digest(updated),
            "modified": updated != original}


def rollback_channel(path, transaction):
    """Restore only if the file is still precisely the version we installed."""
    if not transaction["modified"]:
        return False
    current, info = _read_regular(path)
    if _digest(current) != transaction["installed_sha256"]:
        raise ConfigError("Hostapd changed externally; refusing unsafe rollback")
    _replace_bytes(path, transaction["original"], info)
    return True
