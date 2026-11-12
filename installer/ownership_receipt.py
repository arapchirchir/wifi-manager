"""Safe draft of a Techworld interface creation receipt.

Only intended for a private, root-owned runtime directory after the future
installer sets it up. This module does not create network interfaces or
remove them. Ownership records are evidence, not authorization by themselves:
cleanup must compare the live ifindex/type and never use name-only deletion.
"""
import json
import os
from pathlib import Path
import stat
import tempfile

from installer.resource_ownership import validate_inventory


def write_new_receipt(path, inventory):
    """Create a receipt without following symlinks or replacing existing state.

    The parent directory must already exist and be private to the executing
    user. In production it must be created root-owned with mode 0700.
    """
    validate_inventory(inventory)
    path = Path(path)
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Receipt directory must be a private, real directory")
    if info.st_uid != os.geteuid():
        raise ValueError("Receipt directory is not owned by the running user")
    if path.exists() or path.is_symlink():
        raise FileExistsError("An interface receipt already exists")

    fd, tmp = tempfile.mkstemp(prefix=".receipt-", dir=str(parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(inventory, f, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        # Hard-link creation is exclusive. Unlike os.replace, this cannot
        # silently overwrite another receipt created concurrently.
        os.link(tmp, path, follow_symlinks=False)
        dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        os.unlink(tmp)


def read_receipt(path):
    """Reject symlinks, permissive files and inconsistent inventory."""
    path = Path(path)
    parent = path.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Unsafe receipt directory")
    if info.st_uid != os.geteuid():
        raise ValueError("Receipt directory ownership mismatch")

    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        file_info = os.fstat(fd)
        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError("Receipt must be a regular file")
        if file_info.st_uid != os.geteuid() or file_info.st_mode & 0o077:
            raise ValueError("Unsafe receipt ownership or permissions")
        if file_info.st_size > 16384:
            raise ValueError("Receipt is unexpectedly large")
        with os.fdopen(fd, "r", encoding="utf-8") as f:
            fd = -1
            data = json.load(f)
    finally:
        if fd != -1:
            os.close(fd)
    validate_inventory(data)
    return data
