"""Wake-word diagnostic — listens to default mic, prints OpenWakeWord scores.

Run with:
    .venv/Scripts/python.exe scripts/diag_wake_word.py

Tells us:
- Is the mic actually capturing audio (RMS levels)
- What scores OpenWakeWord assigns when user says wake word
- Whether the issue is mic, model recognition, or threshold
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
CHUNK_SIZE = 1280  # 80ms — minimum for OpenWakeWord


def list_devices() -> None:
    print("=== Audio input devices ===")
    default_idx = sd.default.device[0]
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] <= 0:
            continue
        marker = " <-- DEFAULT" if i == default_idx else ""
        try:
            name = d["name"]
        except Exception:
            name = "<unreadable>"
        print(f"  [{i}] {name} (in={d['max_input_channels']}, rate={d['default_samplerate']:.0f}){marker}")
    print()


def run(device: int | None, duration: float, save_path: Path | None) -> None:
    list_devices()
    print(f"Loading OpenWakeWord...")
    model = Model()
    print(f"Loaded models: {list(model.models.keys())}\n")
    if device is not None:
        sd.default.device = (device, sd.default.device[1])
    chosen = sd.default.device[0]
    print(f"Recording from device idx={chosen}, rate={SAMPLE_RATE}, chunk={CHUNK_SIZE}")
    print(f"Duration: {duration:.0f}s. Speak 'Hey Jarvis' / 'Джарвис' multiple times.\n")
    print(f"{'time':>6} | {'RMS':>8} | top3 scores")
    print("-" * 80)

    captured: list[np.ndarray] = []
    start = time.time()
    chunk_count = 0
    max_scores: dict[str, float] = {}

    def callback(indata, frames, time_info, status):
        nonlocal chunk_count
        if status:
            print(f"[STATUS] {status}")
        audio = indata[:, 0].astype(np.float32)
        captured.append(audio.copy())
        rms = float(np.sqrt(np.mean(audio**2)))
        audio_int16 = (audio * 32767).astype(np.int16)
        prediction = model.predict(audio_int16)
        chunk_count += 1

        # Track max
        for name, score in prediction.items():
            max_scores[name] = max(max_scores.get(name, 0.0), float(score))

        # Print every ~0.5s OR when ANY score > 0.05
        any_loud = any(s > 0.05 for s in prediction.values())
        if chunk_count % 6 == 0 or any_loud:
            tops = sorted(prediction.items(), key=lambda x: x[1], reverse=True)[:3]
            tops_str = "  ".join(f"{n}={s:.3f}" for n, s in tops)
            t = time.time() - start
            marker = "  <-- HIGH" if any_loud else ""
            print(f"{t:6.1f} | {rms:8.5f} | {tops_str}{marker}")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            blocksize=CHUNK_SIZE,
            callback=callback,
            dtype="float32",
        ):
            while time.time() - start < duration:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nInterrupted.")

    print("\n=== Summary ===")
    total_audio = np.concatenate(captured) if captured else np.zeros(0)
    if total_audio.size > 0:
        overall_rms = float(np.sqrt(np.mean(total_audio**2)))
        peak = float(np.max(np.abs(total_audio)))
        print(f"Total samples captured: {total_audio.size} ({total_audio.size / SAMPLE_RATE:.1f}s)")
        print(f"Overall RMS: {overall_rms:.5f}  (rule of thumb: > 0.001 = mic working)")
        print(f"Peak amplitude: {peak:.4f}  (1.0 = full scale)")
    print(f"Max scores per model:")
    for name, score in sorted(max_scores.items(), key=lambda x: -x[1]):
        verdict = "TRIGGERED" if score >= 0.30 else ("WEAK" if score > 0.10 else "FLAT")
        print(f"  {name}: {score:.4f}  [{verdict}]")

    if save_path:
        try:
            import scipy.io.wavfile as wav

            wav.write(str(save_path), SAMPLE_RATE, (total_audio * 32767).astype(np.int16))
            print(f"\nSaved recording to: {save_path}")
        except ImportError:
            print("\n(scipy not available — skipped WAV save)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", type=int, default=None, help="Input device index (use --list to see options)")
    parser.add_argument("--list", action="store_true", help="List devices and exit")
    parser.add_argument("--duration", type=float, default=15.0, help="Recording duration in seconds")
    parser.add_argument("--save", type=Path, default=None, help="Save recorded audio to this WAV path")
    args = parser.parse_args()

    if args.list:
        list_devices()
        return 0
    run(args.device, args.duration, args.save)
    return 0


if __name__ == "__main__":
    sys.exit(main())
