"""Frozen-bundle smoke: proves the voice-critical paths of a built
dist_premium/kali-backend actually work (headless tests cannot see
DLL/lazy-import breakage — three such mines were live 2026-07-13).

Boot the bundle first, then:

    .venv\\Scripts\\python.exe scripts\\frozen_smoke.py --port 3007

BOOT IT OFFLINE — this is load-bearing, not a nicety:

    $env:KALI_PORT="3007"; $env:HF_HUB_OFFLINE="1"
    dist_premium\\kali-backend\\kali-backend.exe

Why: `whisper` passed on 1.0.0-rc1 while the bundled model was NEVER used — the
dev machine's GLOBAL cache (~/.cache/huggingface) happened to hold the same
model, so the check validated the machine, not the bundle. It only surfaced
(2026-07-15) once that global cache was gone. With HF_HUB_OFFLINE=1 a bundle
that has drifted back to the network/global cache FAILS here instead of lying.

Checks (each PASS/FAIL, exit 1 on any FAIL):
  health    — /health answers, version matches kernel.__init__
  whisper   — /voice/transcribe on a synthetic tone decodes via av+ctranslate2
              (exercises the import chain; empty text is fine)
  f5        — /tts returns >0.2s of audio (transformers-5 rthook + CUDA F5)
  reel      — /skills/{name}/reel returns an MP4 (PyAV libopenh264 encode)
  gpl       — bundle av.libs has no libx264/libx265 and has the LGPL license
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # `import kernel` for the version cross-check
BUNDLE = ROOT / "dist_premium" / "kali-backend"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<8} {detail}", flush=True)


def _get(url: str, timeout: float = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, body: dict, timeout: float = 180) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=3007)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    print(f"=== Frozen smoke vs {base} ===")

    # health + version
    try:
        h = _get(f"{base}/health")
        import kernel

        ok = h.get("status") == "ok" and h.get("version") == kernel.__version__
        check("health", ok, f"status={h.get('status')} version={h.get('version')}")
    except Exception as e:
        check("health", False, repr(e))

    # whisper import chain: 0.5s of silence-ish tone, 16kHz i16 LE
    try:
        import numpy as np

        t = np.linspace(0, 0.5, 8000, dtype=np.float32)
        tone = (np.sin(2 * np.pi * 440 * t) * 3000).astype("<i2")
        status, body, _ = _post(
            f"{base}/voice/transcribe",
            {"audio_b64": base64.b64encode(tone.tobytes()).decode(),
             "sample_rate": 16000, "language": "ru"},
        )
        # 200 (decoded, любой текст) = import chain alive; 500 = the DLL mine.
        check("whisper", status == 200, f"http={status} body={body[:60]!r}")
    except Exception as e:
        check("whisper", False, repr(e))

    # F5 synth
    try:
        status, body, ctype = _post(
            f"{base}/tts", {"text": "Проверка синтеза, сэр.", "language": "ru"}
        )
        audio_ok = status == 200 and len(body) > 20000
        check("f5", audio_ok, f"http={status} bytes={len(body)} type={ctype}")
    except Exception as e:
        check("f5", False, repr(e))

    # reel (first available skill)
    try:
        skills = _get(f"{base}/skills")
        name = skills[0]["name"] if skills else None
        if not name:
            check("reel", False, "no skills to render")
        else:
            with urllib.request.urlopen(f"{base}/skills/{name}/reel", timeout=300) as r:
                data = r.read()
            is_mp4 = len(data) > 50000 and b"ftyp" in data[:64]
            check("reel", is_mp4, f"skill={name} bytes={len(data)} mp4={is_mp4}")
    except Exception as e:
        check("reel", False, repr(e))

    # license cleanliness of the shipped bundle
    av_libs = BUNDLE / "_internal" / "av.libs"
    gpl = [p.name for p in av_libs.glob("*x26*")] if av_libs.is_dir() else ["av.libs missing"]
    lic = (av_libs / "FFMPEG-LGPL-LICENSE.txt").exists()
    check("gpl", not gpl and lic, f"x264/x265={gpl or 'none'} lgpl-license={lic}")

    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
