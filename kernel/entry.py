"""PyInstaller entry point — freeze_support + thread limits BEFORE any imports.

This file MUST be the PyInstaller entry point instead of main.py.
It prevents fork bombs by calling freeze_support() before torch/onnxruntime
get a chance to spawn worker processes.
"""
import multiprocessing
multiprocessing.freeze_support()

import os
import sys

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

    # Lock file to prevent multiple instances
    _lock_path = os.path.join(
        os.environ.get("APPDATA", os.path.dirname(sys.executable)),
        "KALI", "kali-backend.lock",
    )
    os.makedirs(os.path.dirname(_lock_path), exist_ok=True)
    try:
        # Try to create lock file exclusively
        _lock_fd = os.open(_lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(_lock_fd, str(os.getpid()).encode())
        os.close(_lock_fd)
    except FileExistsError:
        # Lock exists — check if the other process is alive
        try:
            with open(_lock_path) as f:
                old_pid = int(f.read().strip())
            # Check if process with that PID is running
            os.kill(old_pid, 0)
            # Process alive — exit silently
            sys.exit(0)
        except (ValueError, OSError, ProcessLookupError):
            # Stale lock — overwrite it
            with open(_lock_path, "w") as f:
                f.write(str(os.getpid()))

    import atexit
    def _remove_lock() -> None:
        try:
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
