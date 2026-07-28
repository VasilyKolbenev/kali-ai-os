"""Child process for the H7-3 crash-window tests.

Runs the real FFmpeg subtree transaction and dies HARD (``os._exit``) inside a chosen
journal window — no unwinding, no ``finally``, no lock release by the process itself,
exactly like a power cut or a kill. Usage::

    python _ffmpeg_crash_child.py <dist_premium> <build_dir> <phase>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import fetch_lgpl_ffmpeg as fl  # noqa: E402


def main() -> int:
    dist, build_dir, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

    def hook(reached: str) -> None:
        if reached == phase:
            os._exit(9)

    fl.install_into_sot(build_dir, dist, crash_hook=hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
