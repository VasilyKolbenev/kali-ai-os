"""Compose a 9:16 MP4 reel: animated card frames + the agent voice clip."""
import io
from pathlib import Path

import av
import numpy as np
import qrcode
from PIL import Image, ImageDraw

_W, _H, _FPS = 720, 1280, 30
_VCODEC = "libopenh264"  # LGPL-safe H.264 (spec §3.1) — do NOT swap to libx264
_TAIL_S = 1.2  # closing "scan to install" frame after the voice ends
_BG = (15, 15, 19)
_ACCENT = (120, 200, 255)
_WHITE = (245, 245, 245)


def _amplitude_envelope(audio: np.ndarray, n: int) -> np.ndarray:
    """Down-sample ``|audio|`` into ``n`` buckets in [0,1] for the waveform bars.

    Args:
        audio: Mono float audio samples.
        n: Number of buckets / bars to produce.

    Returns:
        Array of ``n`` peak amplitudes normalized to [0, 1].
    """
    if audio.size == 0 or n <= 0:
        return np.zeros(max(n, 0), dtype=np.float32)
    mag = np.abs(audio)
    buckets = np.array_split(mag, n)
    env = np.array([float(b.max()) if b.size else 0.0 for b in buckets], dtype=np.float32)
    peak = float(env.max()) or 1.0
    return env / peak


def _qr_image(link: str, size: int) -> Image.Image:
    """Render ``link`` as a square RGB QR code of ``size`` pixels.

    Args:
        link: The deep-link payload to encode.
        size: Output side length in pixels.

    Returns:
        An RGB ``size``×``size`` QR image.
    """
    qr = qrcode.QRCode(border=2)
    qr.add_data(link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img.convert("RGB").resize((size, size))


def _render_frame(
    frame_idx: int, n_voice_frames: int, env: np.ndarray, *,
    title: str, subtitle: str, intro_text: str, qr: Image.Image,
) -> Image.Image:
    """Render one RGB frame.

    During the voice segment this draws an animated waveform plus captions;
    during the tail it draws the QR "scan to install" frame.

    Args:
        frame_idx: Index of the frame being rendered.
        n_voice_frames: Number of frames covering the voice clip.
        env: Amplitude envelope for the waveform bars.
        title: Agent title shown top-left.
        subtitle: Agent subtitle shown under the title.
        intro_text: Caption shown during the voice segment.
        qr: Pre-rendered QR image for the tail frame.

    Returns:
        A fully rendered RGB frame.
    """
    img = Image.new("RGB", (_W, _H), _BG)
    d = ImageDraw.Draw(img)
    d.text((48, 96), title, fill=_WHITE)
    d.text((48, 150), subtitle, fill=_ACCENT)
    if frame_idx < n_voice_frames:
        bars = len(env)
        if bars:
            bw = (_W - 96) // bars
            t = frame_idx / max(n_voice_frames - 1, 1)
            for i, e in enumerate(env):
                pulse = e * (0.5 + 0.5 * np.sin(8 * np.pi * t + i))
                h = int(40 + pulse * 300)
                x = 48 + i * bw
                d.rectangle(
                    [x, _H // 2 - h // 2, x + bw - 4, _H // 2 + h // 2], fill=_ACCENT
                )
        d.text((48, _H - 220), intro_text, fill=_WHITE)
    else:
        img.paste(qr, ((_W - qr.width) // 2, _H // 2 - qr.height // 2))
        d.text((48, _H // 2 + qr.height // 2 + 24), "Сканируй, чтобы установить", fill=_WHITE)
    return img


def _encode_video(container: "av.container.OutputContainer", vstream: "av.stream.Stream",
                  n_frames: int, n_voice_frames: int, env: np.ndarray, *, title: str,
                  subtitle: str, intro_text: str, qr: Image.Image) -> None:
    """Encode and mux all video frames into ``container``.

    Args:
        container: Open output container in write mode.
        vstream: The pre-created video stream to encode into.
        n_frames: Total number of frames to render.
        n_voice_frames: Number of frames covering the voice clip.
        env: Amplitude envelope for the waveform bars.
        title: Agent title.
        subtitle: Agent subtitle.
        intro_text: Voice-segment caption.
        qr: Pre-rendered QR image for the tail frame.
    """
    for i in range(n_frames):
        img = _render_frame(
            i, n_voice_frames, env, title=title, subtitle=subtitle,
            intro_text=intro_text, qr=qr,
        )
        vframe = av.VideoFrame.from_image(img)
        for packet in vstream.encode(vframe):
            container.mux(packet)
    for packet in vstream.encode():  # flush video
        container.mux(packet)


def _encode_audio(container: "av.container.OutputContainer",
                 astream: "av.stream.Stream", audio: np.ndarray, sr: int) -> None:
    """Encode the voice clip to AAC and mux it into ``container``.

    Transcodes via a WAV round-trip so the resampler handles AAC's required
    frame size and planar-float layout.

    Args:
        container: Open output container in write mode.
        astream: The pre-created AAC audio stream to encode into.
        audio: Mono float audio samples.
        sr: Sample rate in Hz.
    """
    from kernel.voice.tts_router import audio_to_wav_bytes

    wav = io.BytesIO(audio_to_wav_bytes(audio, sr))
    with av.open(wav, mode="r") as src:
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
        for aframe in src.decode(audio=0):
            for rframe in resampler.resample(aframe):
                for packet in astream.encode(rframe):
                    container.mux(packet)
        for rframe in resampler.resample(None):  # flush resampler
            for packet in astream.encode(rframe):
                container.mux(packet)
        for packet in astream.encode():  # flush encoder
            container.mux(packet)


def compose_reel(
    audio: np.ndarray, sr: int, *, title: str, subtitle: str,
    intro_text: str, link: str, out_path: Path,
) -> Path:
    """Render a 9:16 MP4 to ``out_path``.

    Draws an animated card over the voice clip, ending on a QR "scan to
    install" frame. Raises on encode failure.

    Args:
        audio: Normalized float32-mono voice clip.
        sr: Sample rate in Hz.
        title: Agent title shown on the card.
        subtitle: Agent subtitle shown on the card.
        intro_text: Caption shown during the voice segment.
        link: Deep-link encoded into the closing QR frame.
        out_path: Destination MP4 path.

    Returns:
        ``out_path``.
    """
    if sr <= 0:
        raise ValueError(f"compose_reel: sample rate must be positive, got {sr}")
    if audio.size == 0:
        raise ValueError("compose_reel: empty voice clip — refusing to render a silent reel")
    duration_s = (audio.size / sr) + _TAIL_S
    n_frames = max(int(duration_s * _FPS), 1)
    n_voice_frames = max(int((audio.size / sr) * _FPS), 1)
    env = _amplitude_envelope(audio, n=48)
    qr = _qr_image(link, size=380)

    with av.open(str(out_path), mode="w") as container:
        # Add both streams before any mux so the muxer finalizes both
        # time_bases when it writes the header (PyAV 17: a stream added after
        # the header is written gets a zero time_base → "rebase to zero time").
        vstream = container.add_stream(_VCODEC, rate=_FPS)
        vstream.width, vstream.height, vstream.pix_fmt = _W, _H, "yuv420p"
        astream = container.add_stream("aac", rate=sr)
        astream.format = "fltp"
        astream.layout = "mono"
        _encode_video(
            container, vstream, n_frames, n_voice_frames, env, title=title,
            subtitle=subtitle, intro_text=intro_text, qr=qr,
        )
        _encode_audio(container, astream, audio, sr)
    return out_path
