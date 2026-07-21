"""OPUS-102 #5: a blocked model loader must NOT hold the backend process past
the shutdown SLA. Cancelling the asyncio wrapper is not enough — the loader runs
in a daemon thread, so the interpreter abandons it and the process exits ≤2s.

Process-level: a child interpreter registers blocked loaders (coordinator prewarm
+ a simulated auto_start/pipeline load + a warmup), initiates shutdown, and must
terminate within the SLA. Run as a subprocess so a real interpreter-exit is
exercised (not just the asyncio layer).
"""
from __future__ import annotations

import subprocess
import sys

_CHILD = r"""
import asyncio, time
from kernel.model_coordinator import ModelCoordinator

def _blocked():
    time.sleep(30)   # a loader that never finishes within the test

async def main():
    c = ModelCoordinator(default_timeout=60)
    # coordinator prewarm loaders
    c.register("tts", _blocked, lambda: False)
    c.register("stt", _blocked, lambda: False)
    # simulated auto_start pipeline component load (same daemon mechanism)
    c.register("vad", _blocked, lambda: False)
    c.prewarm(["tts", "stt", "vad"])
    # simulated warmup synth via run_blocking
    warmup = asyncio.create_task(c.run_blocking(_blocked))
    await asyncio.sleep(0.3)  # let the daemon loaders start
    t0 = time.perf_counter()
    warmup.cancel()
    await c.shutdown()
    print("SHUTDOWN_SECS=%.3f" % (time.perf_counter() - t0), flush=True)

asyncio.run(main())
print("EXITED", flush=True)
"""


def test_blocked_loader_does_not_hold_process_after_shutdown() -> None:
    # If the loader threads were non-daemon, interpreter exit would join them and
    # hang ~30s → TimeoutExpired. Daemon threads let the process exit immediately.
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        timeout=15,  # generous for interpreter + import startup; the 30s loader must NOT gate it
    )
    assert proc.returncode == 0, f"child failed: {proc.stderr[-2000:]}"
    assert "EXITED" in proc.stdout, proc.stdout
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("SHUTDOWN_SECS=")), "")
    assert line, proc.stdout
    shutdown_secs = float(line.split("=", 1)[1])
    assert shutdown_secs <= 2.0, f"shutdown took {shutdown_secs:.3f}s (> 2s SLA)"
