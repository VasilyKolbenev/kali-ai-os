"""OPUS-102 #5: a blocked model loader must NOT hold the backend process past
the shutdown SLA. Loaders run in daemon threads → the interpreter abandons them
and the process exits ≤2s. Measured at PROCESS level (parent-observed wall time
from "loaders started" to actual process exit), not only the coroutine shutdown.

Actual frozen close-during-load remains a live gate for OPUS-103.
"""
from __future__ import annotations

import subprocess
import sys
import time

_CHILD = r"""
import asyncio, time, sys
from kernel.model_coordinator import ModelCoordinator

def _blocked():
    time.sleep(30)   # a loader that never finishes within the test

async def main():
    c = ModelCoordinator(default_timeout=60)
    c.register("tts", _blocked, lambda: False)
    c.register("stt", _blocked, lambda: False)
    c.register("vad", _blocked, lambda: False)   # simulated auto_start component
    c.prewarm(["tts", "stt", "vad"])
    warmup = asyncio.create_task(c.run_blocking(_blocked))   # simulated warmup synth
    await asyncio.sleep(0.3)  # let the daemon loaders start
    print("LOADERS_STARTED", flush=True)
    t0 = time.perf_counter()
    warmup.cancel()
    await c.shutdown()
    print("SHUTDOWN_SECS=%.3f" % (time.perf_counter() - t0), flush=True)

asyncio.run(main())
print("EXITED", flush=True)
"""


def test_blocked_loader_does_not_hold_process_after_shutdown() -> None:
    # daemon loader threads → interpreter abandons them at exit. If they were
    # non-daemon, interpreter exit would join the 30s loaders and hang.
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Parent-observed clock starts when the child reports its loaders are running.
    t_started: float | None = None
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("LOADERS_STARTED"):
            t_started = time.perf_counter()
            break
    assert t_started is not None, "child never reported LOADERS_STARTED"

    try:
        rest, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError("process did not exit after shutdown (blocked loader held it)")
    exit_secs = time.perf_counter() - t_started

    assert proc.returncode == 0, f"child failed: {err[-2000:]}"
    assert "EXITED" in rest, rest
    # Parent-observed: from loaders-started to actual process exit within the SLA.
    assert exit_secs <= 2.0, f"process took {exit_secs:.3f}s from loaders-started to exit (> 2s SLA)"
    line = next((ln for ln in rest.splitlines() if ln.startswith("SHUTDOWN_SECS=")), "")
    assert line, rest
    assert float(line.split("=", 1)[1]) <= 2.0
