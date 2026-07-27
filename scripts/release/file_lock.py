"""Cross-process advisory file lock for the release pipeline (H6-2).

The stage swap and the premium_assets source-of-truth both need one writer at a time,
across processes. This is the shared primitive behind both:

* the lock lives in an OS lock on a byte of an anchor FILE, so the OS releases it when
  the holder dies — a leftover lock file never blocks, only a live holder does;
* it is non-blocking: a busy lock raises immediately rather than queueing a second
  multi-GB build behind the first;
* on Windows ``msvcrt.locking`` also refuses a SECOND handle from the SAME process, so
  a nested acquisition is a programming error that surfaces as LockBusy rather than a
  silent double-entry (callers pass ``_held=True`` down instead of re-locking).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover - build tooling is Windows; POSIX kept for CI/dev
    import fcntl


class LockBusy(Exception):
    """The lock is held by a live holder (fail fast, never queue)."""


def acquire(path: Path) -> int:
    """Take the lock anchored at ``path``; returns the fd that OWNS it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR)
    try:
        os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        raise LockBusy(f"{path} held by another process") from e
    return fd


def release(fd: int) -> None:
    """Release the lock by closing the owning fd (the anchor file persists)."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        if sys.platform == "win32":
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover
            fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    os.close(fd)
