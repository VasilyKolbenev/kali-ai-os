"""PyInstaller entry point — freeze_support + thread limits BEFORE any imports.

This file MUST be the PyInstaller entry point instead of main.py.
It prevents fork bombs by calling freeze_support() before torch/onnxruntime
get a chance to spawn worker processes.
"""
import multiprocessing
multiprocessing.freeze_support()

import os
import sys


def _acquire_single_instance_lock(lock_path: str) -> int | None:
    """Hold an exclusive OS lock on ``lock_path`` for the process lifetime.

    The returned fd is kept open forever: the OS releases the lock on ANY
    process death (crash, TerminateProcess), so stale locks cannot exist and
    the PID-reuse lottery of the old liveness check is gone. The file content
    (our PID) is informational only — the lock itself is the byte-range lock.

    Args:
        lock_path: Path to the lock file (created if missing).

    Returns:
        The open fd holding the lock, or None if another live instance
        already holds it.
    """
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd

# Prevent torch/OMP/MKL from spawning worker threads in frozen mode
if hasattr(sys, "_MEIPASS"):
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    # Tell torch to use single thread for intra-op parallelism
    os.environ.setdefault("TORCH_NUM_THREADS", "1")

    # HuggingFace cache: a NORMALIZED absolute path under _internal (no ".."
    # segments). Frozen Python raises [Errno 22] traversing HF snapshot symlinks
    # when the cache path contains ".." (as the old __file__-relative path did),
    # which silently broke the F5 vocoder (vocos) and Whisper STT. Set it here,
    # before any HF-using import, so every code path agrees. Fall back to a
    # per-user dir if the install dir is read-only (all-users install).
    _hf_cache = os.path.join(sys._MEIPASS, ".hf_cache")
    try:
        os.makedirs(_hf_cache, exist_ok=True)
    except OSError:
        _hf_cache = os.path.join(
            os.environ.get("LOCALAPPDATA", os.path.dirname(sys.executable)),
            "KALI", ".hf_cache",
        )
        os.makedirs(_hf_cache, exist_ok=True)
    os.environ["HF_HOME"] = os.path.normpath(_hf_cache)
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

    # If the cache already holds the voice-model snapshots, run fully
    # offline: otherwise every start pings huggingface.co (HEAD/GET version
    # checks) which slows startup and breaks no-network first runs.
    _hub_dir = os.path.join(os.environ["HF_HOME"], "hub")
    _required_snapshots = [
        os.path.join(_hub_dir, "models--charactr--vocos-mel-24khz", "snapshots"),
        os.path.join(_hub_dir, "models--Systran--faster-whisper-small", "snapshots"),
    ]
    try:
        if all(os.path.isdir(p) and os.listdir(p) for p in _required_snapshots):
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    except OSError:
        pass  # cache unreadable — stay online, downloads may still work

    # Single instance: exclusive lock held for the whole process lifetime.
    _lock_path = os.path.join(
        os.environ.get("APPDATA", os.path.dirname(sys.executable)),
        "KALI", "kali-backend.lock",
    )
    _lock_fd = _acquire_single_instance_lock(_lock_path)
    if _lock_fd is None:
        # Logging isn't configured this early — leave a breadcrumb in the
        # usual log file so a refused start is diagnosable, then exit.
        try:
            from datetime import datetime
            _log_dir = os.path.join(os.environ.get("APPDATA", "."), "KALI", "logs")
            os.makedirs(_log_dir, exist_ok=True)
            with open(
                os.path.join(_log_dir, "kali-backend.log"), "a", encoding="utf-8"
            ) as _f:
                _f.write(
                    f"{datetime.now():%Y-%m-%d %H:%M:%S,000} [WARNING] "
                    f"kernel.entry: another instance holds {_lock_path}; exiting\n"
                )
        except OSError:
            pass
        sys.exit(0)

    import atexit
    def _remove_lock() -> None:
        try:
            os.close(_lock_fd)
            os.unlink(_lock_path)
        except OSError:
            pass
    atexit.register(_remove_lock)


def _setup_logging() -> None:
    """Configure root logger: console + rotating file in %APPDATA%/KALI/logs/.

    Having a durable log file is critical — users report "something doesn't work"
    and we need to grep their log without asking them to re-run from a terminal.
    """
    import logging
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    log_dir = Path(os.environ.get("APPDATA", ".")) / "KALI" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "kali-backend.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    # 5 MB × 5 rotations = 25 MB cap
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.INFO)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    logging.getLogger("kernel.voice").setLevel(logging.DEBUG)
    logging.getLogger().info("Logging initialized at %s", log_file)


def main() -> None:
    """Run the KALI kernel."""
    import uvicorn
    from kernel.main import create_app

    _setup_logging()

    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("KALI_HOST", "127.0.0.1"),
        port=int(os.environ.get("KALI_PORT", "3005")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
