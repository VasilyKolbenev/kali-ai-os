from pathlib import Path

import av
import numpy as np
import pytest

from kernel.reel.compose import _VCODEC, compose_reel


def test_vcodec_is_lgpl_safe() -> None:
    """Fix 4: guard against an accidental swap to GPL libx264."""
    assert _VCODEC == "libopenh264"


def _probe(path: Path) -> dict:
    with av.open(str(path)) as c:
        video = [s for s in c.streams if s.type == "video"]
        audio = [s for s in c.streams if s.type == "audio"]
        audio_samples = 0
        if audio:
            for fr in c.decode(audio=0):
                audio_samples += fr.samples
        return {
            "video": len(video),
            "audio": len(audio),
            "vcodec": video[0].codec_context.name if video else None,
            "duration_s": float(c.duration) / av.time_base if c.duration else 0.0,
            "audio_samples": audio_samples,
        }


def test_compose_reel_produces_mp4_with_av_streams(tmp_path: Path) -> None:
    sr = 24000
    audio = (0.1 * np.sin(np.linspace(0, 220, sr * 1))).astype(np.float32)  # ~1s tone
    out = tmp_path / "reel.mp4"
    result = compose_reel(
        audio, sr,
        title="chef", subtitle="повар-помощник",
        intro_text="Привет! Я повар-помощник.",
        link="kali://import?n=chef&d=AAAA",
        out_path=out,
    )
    assert result == out and out.exists() and out.stat().st_size > 0
    info = _probe(out)
    assert info["video"] == 1
    assert info["audio"] == 1
    assert info["vcodec"] in {"h264", "libopenh264"}
    assert 0.8 <= info["duration_s"] <= 4.0  # ~1s audio + closing frame padding
    assert info["audio_samples"] >= sr * 0.8  # Fix 1: real decoded samples, not just stream present


def test_compose_reel_raises_on_empty_audio(tmp_path: Path) -> None:
    """Fix 2: empty voice clip must raise ValueError, not emit a silent reel."""
    out = tmp_path / "silent.mp4"
    with pytest.raises(ValueError, match="empty voice clip"):
        compose_reel(
            np.array([], dtype=np.float32), 24000,
            title="chef", subtitle="повар-помощник",
            intro_text="Привет! Я повар-помощник.",
            link="kali://import?n=chef&d=AAAA",
            out_path=out,
        )
