"""Analyze frequency profile of reference Sound Pack vs RVC output.

Computes average spectral envelope of reference files, compares with
RVC output, and generates a matching EQ curve.

Usage:
    cd C:/Users/User/Desktop/Jarvis
    uv run python services/tts/analyze_eq.py
"""

import logging
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SOUNDPACK_DIR = Path("C:/Users/User/Desktop/Jarvis/Jarvis Sound Pack \u043e\u0442 Jarvis Desktop")
RVC_OUTPUT = Path("C:/Users/User/Desktop/Jarvis/test_ab_jarvis_v2.wav")
PROJECT_ROOT = Path("C:/Users/User/Desktop/Jarvis")

# Frequency bands for analysis
BANDS = [
    ("sub_bass", 20, 60),
    ("bass", 60, 250),
    ("low_mid", 250, 500),
    ("mid", 500, 2000),
    ("upper_mid", 2000, 4000),
    ("presence", 4000, 6000),
    ("brilliance", 6000, 10000),
    ("air", 10000, 20000),
]


def compute_spectral_profile(audio: np.ndarray, sr: int) -> dict[str, float]:
    """Compute average energy per frequency band."""
    spectrum = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sr)

    profile = {}
    total_energy = np.sum(spectrum ** 2)

    for name, low, high in BANDS:
        mask = (freqs >= low) & (freqs < high)
        band_energy = np.sum(spectrum[mask] ** 2)
        profile[name] = band_energy / max(total_energy, 1e-10)

    return profile


def main() -> None:
    """Analyze and compare frequency profiles."""
    # Load all reference files
    ref_profiles = []
    wav_files = list(SOUNDPACK_DIR.glob("*.wav"))
    logger.info("Found %d reference WAV files", len(wav_files))

    for wav_path in wav_files:
        try:
            audio, sr = sf.read(str(wav_path))
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            # Resample to 40kHz for fair comparison
            if sr != 40000:
                new_len = int(len(audio) * 40000 / sr)
                audio = np.interp(
                    np.linspace(0, len(audio) - 1, new_len),
                    np.arange(len(audio)),
                    audio,
                ).astype(np.float32)
            profile = compute_spectral_profile(audio, 40000)
            ref_profiles.append(profile)
        except Exception as e:
            logger.warning("Skipping %s: %s", wav_path.name, e)

    if not ref_profiles:
        logger.error("No reference files loaded!")
        return

    # Average reference profile
    avg_ref = {}
    for band_name, _, _ in BANDS:
        values = [p[band_name] for p in ref_profiles]
        avg_ref[band_name] = np.mean(values)

    # Load RVC output
    rvc_audio, rvc_sr = sf.read(str(RVC_OUTPUT))
    if rvc_sr != 40000:
        new_len = int(len(rvc_audio) * 40000 / rvc_sr)
        rvc_audio = np.interp(
            np.linspace(0, len(rvc_audio) - 1, new_len),
            np.arange(len(rvc_audio)),
            rvc_audio,
        ).astype(np.float32)
    rvc_profile = compute_spectral_profile(rvc_audio, 40000)

    # Print comparison
    logger.info("")
    logger.info("=" * 70)
    logger.info("FREQUENCY PROFILE COMPARISON")
    logger.info("=" * 70)
    logger.info("%-15s  %-8s  %-10s  %-10s  %-10s", "Band", "Hz", "Reference", "RVC v2", "Ratio")
    logger.info("-" * 70)

    eq_gains = {}
    for band_name, low, high in BANDS:
        ref_val = avg_ref[band_name]
        rvc_val = rvc_profile[band_name]
        ratio = ref_val / max(rvc_val, 1e-10)

        # Clamp ratio to reasonable range
        ratio_clamped = max(0.01, min(10.0, ratio))
        eq_gains[band_name] = ratio_clamped

        logger.info(
            "%-15s  %4d-%5d  %8.4f  %8.4f  %8.2fx %s",
            band_name, low, high, ref_val, rvc_val, ratio,
            "<<< BOOST" if ratio > 1.5 else (">>> CUT" if ratio < 0.5 else ""),
        )

    logger.info("")
    logger.info("=" * 70)
    logger.info("RECOMMENDED EQ GAINS (reference / rvc ratio):")
    logger.info("=" * 70)
    for band_name, low, high in BANDS:
        gain = eq_gains[band_name]
        gain_db = 20 * np.log10(max(gain, 1e-10))
        bar = "#" * int(max(0, min(50, gain * 10)))
        logger.info("  %-15s (%5d-%5dHz): gain=%.3f (%.1f dB) %s",
                     band_name, low, high, gain, gain_db, bar)

    # Generate matched output
    logger.info("")
    logger.info("Generating EQ-matched output...")

    rvc_audio_orig, _ = sf.read(str(RVC_OUTPUT))
    spectrum = np.fft.rfft(rvc_audio_orig)
    freqs = np.fft.rfftfreq(len(rvc_audio_orig), 1.0 / 40000)

    gains = np.ones_like(freqs)
    for band_name, low, high in BANDS:
        mask = (freqs >= low) & (freqs < high)
        gains[mask] = eq_gains[band_name]

    # Smooth transitions
    from scipy.ndimage import gaussian_filter1d
    gains = gaussian_filter1d(gains, sigma=20)

    spectrum *= gains
    matched = np.fft.irfft(spectrum, n=len(rvc_audio_orig)).astype(np.float32)

    # Normalize
    peak = np.max(np.abs(matched))
    if peak > 0:
        matched = (matched * 0.7 / peak).astype(np.float32)

    output_path = PROJECT_ROOT / "test_tune_v2_eq_matched.wav"
    sf.write(str(output_path), matched, 40000)
    logger.info("Saved: %s", output_path.name)

    # Print EQ dict for use in code
    logger.info("")
    logger.info("EQ config for code:")
    logger.info("EQ_GAINS = {")
    for band_name, low, high in BANDS:
        logger.info('    "%s": (%.3f, %d, %d),  # gain, low_hz, high_hz',
                     band_name, eq_gains[band_name], low, high)
    logger.info("}")


if __name__ == "__main__":
    main()
