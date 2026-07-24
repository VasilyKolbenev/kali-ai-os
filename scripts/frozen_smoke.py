"""Frozen-bundle smoke: prove a built bundle's voice-critical paths work AND that
it loads them from ITS OWN files, offline — not the dev machine's global cache.

C6 (OPUS-103) makes this a cache-isolated offline-env smoke against the EXACT
stage / installed copy:

    .venv\\Scripts\\python.exe scripts\\frozen_smoke.py \\
        --bundle dist_premium\\premium_stage\\kali-backend \\
        --manifest dist_premium\\premium_stage\\STAGE_MANIFEST.json --port 3007

``--bundle`` and ``--manifest`` are MANDATORY: the smoke first proves the bundle
matches its STAGE_MANIFEST (exact stage), then launches it ITSELF with a fully
isolated cache (HF_HOME/HUGGINGFACE_HUB_CACHE/TRANSFORMERS_CACHE/TORCH_HOME/
XDG_CACHE_HOME point at an empty temp dir) and the offline flags set, external
HTTP proxied to a dead sink (localhost bypasses via NO_PROXY). So a bundle that
has drifted back to the network / global cache FAILS here instead of lying — the
2026-07-15 trap where `whisper` "passed" on the global cache while the shipped
model was never used.

This is a *cache-isolated offline-env* smoke, NOT a physical-offline test:
physical offline is a separate live acceptance on a disconnected network / clean
VM. The SLA is measured from just before the bundle launches: the first
successful HTTP 200 on /live must arrive within 1.0s.

Checks (each PASS/FAIL, exit 1 on any FAIL):
  live      — /live answers 200 within the 1.0s SLA (measured pre-launch)
  health    — /health answers, version matches kernel.__init__
  whisper   — /voice/transcribe on a synthetic tone decodes via av+ctranslate2
  f5        — /tts returns >0.2s of audio
  reel      — /skills/{name}/reel returns an MP4
  gpl       — bundle av.libs has no libx264/libx265 and has the LGPL license
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # `import kernel` for the version cross-check

from scripts.release import stage_policy  # noqa: E402

_CACHE_VARS = ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
               "TORCH_HOME", "XDG_CACHE_HOME")
_OFFLINE_FLAGS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")
_PROXY_SINK = "http://127.0.0.1:1"  # closed port → external HTTP fails fast
_NO_PROXY = "127.0.0.1,localhost,::1"


class SmokeError(Exception):
    """The frozen smoke could not run honestly (bad env / SLA / manifest drift)."""


# ── cache-isolated offline environment ──────────────────────────────────────
def build_offline_env(*, cache_root: Path, base: dict[str, str]) -> dict[str, str]:
    """Child env with every model cache isolated, offline flags on, external HTTP
    sunk to a dead proxy (localhost still reachable via NO_PROXY)."""
    env = dict(base)
    env["HF_HOME"] = str(cache_root / "hf")
    env["HUGGINGFACE_HUB_CACHE"] = str(cache_root / "hf" / "hub")
    env["TRANSFORMERS_CACHE"] = str(cache_root / "transformers")
    env["TORCH_HOME"] = str(cache_root / "torch")
    env["XDG_CACHE_HOME"] = str(cache_root / "xdg")
    for flag in _OFFLINE_FLAGS:
        env[flag] = "1"
    env["HTTP_PROXY"] = env["HTTPS_PROXY"] = _PROXY_SINK
    env["http_proxy"] = env["https_proxy"] = _PROXY_SINK
    env["NO_PROXY"] = env["no_proxy"] = _NO_PROXY
    return env


def assert_offline_env(env: dict[str, str]) -> None:
    """Fail-closed: refuse to run the smoke unless the isolation is complete."""
    missing = [v for v in _CACHE_VARS if not env.get(v)]
    missing += [f for f in _OFFLINE_FLAGS if env.get(f) != "1"]
    if not env.get("HTTP_PROXY") or not env.get("HTTPS_PROXY"):
        missing.append("HTTP(S)_PROXY")
    if "127.0.0.1" not in env.get("NO_PROXY", ""):
        missing.append("NO_PROXY")
    if missing:
        raise SmokeError(f"OFFLINE_ENV incomplete (global cache could mask): {missing}")


# ── args ────────────────────────────────────────────────────────────────────
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cache-isolated offline-env frozen smoke")
    parser.add_argument("--bundle", required=True, help="path to the bundle (kali-backend dir)")
    parser.add_argument("--manifest", required=True, help="path to STAGE_MANIFEST.json")
    parser.add_argument("--port", type=int, default=3007)
    return parser.parse_args(argv)


def verify_bundle_matches_manifest(bundle: Path, manifest_path: Path) -> None:
    """Prove the bundle is the EXACT stage its manifest pins (no drift)."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage_policy.verify_manifest(bundle, manifest)


# ── /live SLA ───────────────────────────────────────────────────────────────
def measure_live_sla(*, poller: Callable[[], "tuple[int, float]"], deadline_s: float,
                     clock: Callable[[], float], sleep: Callable[[float], None],
                     t0: float | None = None) -> tuple[float, float]:
    """Time from ``t0`` (set just before launch) to the first 200 on /live.

    ``poller()`` performs one /live request and returns ``(status, req_latency)``.
    Raises SmokeError if /live is not 200 within ``deadline_s``."""
    origin = t0 if t0 is not None else clock()
    while True:
        status, latency = poller()
        now = clock()
        if status == 200:
            elapsed = now - origin
            if elapsed > deadline_s:
                raise SmokeError(f"SLA: /live 200 took {elapsed:.3f}s > {deadline_s}s")
            return elapsed, latency
        if now - origin > deadline_s:
            raise SmokeError(f"SLA: /live not ready within {deadline_s}s")
        sleep(0.05)


# ── HTTP helpers + checks ───────────────────────────────────────────────────
def check(results: list, name: str, ok: bool, detail: str) -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name:<8} {detail}", flush=True)


def _get(url: str, timeout: float = 30) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def _post(url: str, body: dict, timeout: float = 180) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def run_checks(base: str, bundle: Path) -> list[tuple[str, bool, str]]:
    """Exercise the voice-critical paths against a running bundle."""
    results: list[tuple[str, bool, str]] = []
    try:
        import numpy as np
        h = _get(f"{base}/health")
        import kernel
        ok = h.get("status") == "ok" and h.get("version") == kernel.__version__
        check(results, "health", ok, f"status={h.get('status')} version={h.get('version')}")
    except Exception as e:
        check(results, "health", False, repr(e))
    try:
        t = np.linspace(0, 0.5, 8000, dtype=np.float32)
        tone = (np.sin(2 * np.pi * 440 * t) * 3000).astype("<i2")
        status, body, _ = _post(f"{base}/voice/transcribe",
                                 {"audio_b64": base64.b64encode(tone.tobytes()).decode(),
                                  "sample_rate": 16000, "language": "ru"})
        check(results, "whisper", status == 200, f"http={status} body={body[:60]!r}")
    except Exception as e:
        check(results, "whisper", False, repr(e))
    try:
        status, body, ctype = _post(f"{base}/tts", {"text": "Проверка синтеза, сэр.", "language": "ru"})
        check(results, "f5", status == 200 and len(body) > 20000, f"http={status} bytes={len(body)}")
    except Exception as e:
        check(results, "f5", False, repr(e))
    try:
        skills = _get(f"{base}/skills")
        name = skills[0]["name"] if skills else None
        if not name:
            check(results, "reel", False, "no skills to render")
        else:
            with urllib.request.urlopen(f"{base}/skills/{name}/reel", timeout=300) as r:
                data = r.read()
            check(results, "reel", len(data) > 50000 and b"ftyp" in data[:64],
                  f"skill={name} bytes={len(data)}")
    except Exception as e:
        check(results, "reel", False, repr(e))
    av_libs = bundle / "_internal" / "av.libs"
    gpl = [p.name for p in av_libs.glob("*x26*")] if av_libs.is_dir() else ["av.libs missing"]
    lic = (av_libs / "FFMPEG-LGPL-LICENSE.txt").exists()
    check(results, "gpl", not gpl and lic, f"x264/x265={gpl or 'none'} lgpl-license={lic}")
    return results


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    bundle = Path(ns.bundle).resolve()
    manifest = Path(ns.manifest).resolve()
    base = f"http://127.0.0.1:{ns.port}"
    print(f"=== Frozen smoke (offline-env) vs {base} — bundle {bundle} ===")
    verify_bundle_matches_manifest(bundle, manifest)  # exact stage before we launch it

    with tempfile.TemporaryDirectory() as cache:
        env = build_offline_env(cache_root=Path(cache), base=dict(os.environ))
        env["KALI_PORT"] = str(ns.port)
        assert_offline_env(env)
        exe = bundle / "kali-backend.exe"
        t0 = time.monotonic()  # SLA origin — just before launch
        proc = subprocess.Popen([str(exe)], env=env)

        def _poll() -> tuple[int, float]:
            start = time.monotonic()
            try:
                with urllib.request.urlopen(f"{base}/live", timeout=2) as r:
                    return r.status, time.monotonic() - start
            except Exception:
                return 0, time.monotonic() - start

        results: list[tuple[str, bool, str]] = []
        try:
            elapsed, latency = measure_live_sla(poller=_poll, deadline_s=1.0,
                                                clock=time.monotonic, sleep=time.sleep, t0=t0)
            check(results, "live", True, f"200 in {elapsed:.3f}s (req {latency * 1000:.0f}ms)")
            results += run_checks(base, bundle)
        except SmokeError as e:
            check(results, "live", False, str(e))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILED: ' + ', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
