"""Child process for the H7-5 installer-output crash tests.

Runs the real locked build/seal/promote transaction with a stub ISCC and dies HARD
inside a chosen journal window. Usage::

    python _installer_crash_child.py <dist_premium> <setup_name> <phase>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.release import installer_gate as ig  # noqa: E402


def main() -> int:
    dist, setup_name, phase = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    corrupt = len(sys.argv) > 4 and sys.argv[4] == "corrupt"

    def fake_iscc(cmd):  # noqa: ANN001 — stands in for ISCC: writes the artifacts
        out = Path(cmd[-1][2:])  # the /O<dir> argument this transaction appended
        (out / setup_name).write_bytes(b"NEW-SETUP")
        (out / f"{setup_name[:-4]}-1.bin").write_bytes(b"NEW-1")
        return SimpleNamespace(returncode=0)

    def hook(reached: str) -> None:
        if reached != phase:
            return
        if corrupt:  # damage the promoted output BEFORE the crash
            (dist / "installer" / f"{setup_name[:-4]}-1.bin").write_bytes(b"CORRUPTED")
        os._exit(9)

    ig.build_output(dist, setup_name=setup_name, iscc_cmd=["iscc", "x.iss"],
                    runner=fake_iscc, crash_hook=hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
