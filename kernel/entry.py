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


def main() -> None:
    """Run the KALI kernel."""
    import logging
    import uvicorn
    from kernel.main import create_app

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("kernel.voice").setLevel(logging.DEBUG)

    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("KALI_HOST", "127.0.0.1"),
        port=int(os.environ.get("KALI_PORT", "3005")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
