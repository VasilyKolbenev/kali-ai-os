"""Tests for the single-instance lock in kernel.entry.

The lock must be held by an open fd for the process lifetime so the OS
releases it on any death — these tests simulate a second instance (second
acquire while held), a clean release, and reclaiming a stale file left by
the old PID-based implementation.
"""
import os

from kernel.entry import _acquire_single_instance_lock


def test_acquire_lock_on_free_path_returns_fd(tmp_path):
    lock = str(tmp_path / "test.lock")
    fd = _acquire_single_instance_lock(lock)
    assert fd is not None
    assert os.path.exists(lock)
    os.close(fd)


def test_second_acquire_while_held_returns_none(tmp_path):
    lock = str(tmp_path / "test.lock")
    fd1 = _acquire_single_instance_lock(lock)
    assert fd1 is not None
    fd2 = _acquire_single_instance_lock(lock)
    assert fd2 is None
    os.close(fd1)


def test_reacquire_after_release_succeeds(tmp_path):
    lock = str(tmp_path / "test.lock")
    fd1 = _acquire_single_instance_lock(lock)
    assert fd1 is not None
    # Closing the fd releases the OS lock — same as process death.
    os.close(fd1)
    fd2 = _acquire_single_instance_lock(lock)
    assert fd2 is not None
    os.close(fd2)


def test_stale_file_from_old_version_is_reclaimed(tmp_path):
    lock = str(tmp_path / "test.lock")
    # Old implementation left a PID-content file with no OS lock held.
    with open(lock, "w", encoding="utf-8") as f:
        f.write("99999")
    fd = _acquire_single_instance_lock(lock)
    assert fd is not None
    os.close(fd)
