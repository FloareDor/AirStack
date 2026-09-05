"""Cross-platform, nonblocking one-byte file locks for exclusive trials."""

from __future__ import annotations

import os
from typing import TextIO


def try_lock(stream: TextIO) -> bool:
    """Acquire an exclusive nonblocking lock; return False when it is held."""
    stream.seek(0)
    stream.write("0")
    stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def unlock(stream: TextIO) -> None:
    try:
        if os.name == "nt":
            import msvcrt

            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream, fcntl.LOCK_UN)
    except OSError:
        pass
