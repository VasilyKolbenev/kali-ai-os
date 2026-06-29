# UGC Voice-Reel Share — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a created KALI agent be shared as a short 9:16 MP4 reel in which the agent speaks an auto-generated intro line in its own voice, rendered on the desktop backend and shared from mobile, with honest fallback to the existing PNG card.

**Architecture:** A new pure backend module `kernel/reel/generator.py` (LLM intro line → TTS clip → PyAV/libopenh264 9:16 compose) behind a new `GET /skills/{name}/reel` route that mirrors the existing `/skills/{name}/export` resolution + honest-fail envelope. Mobile's existing `share_to_reels_screen.dart` gains a reel-fetch step that branches on `content-type` and falls back to the PNG card. No on-device encoding; reuses shipped F5/ElevenLabs TTS + libav* DLLs.

**Tech Stack:** Python 3.12 / FastAPI, PyAV (`av`), Pillow, `qrcode`; Flutter (Dart) on the mobile side; pytest (`-m core_loop`, asyncio_mode=auto) + Flutter widget tests.

**Spec:** [`docs/superpowers/specs/2026-06-29-ugc-reel-share-design.md`](../specs/2026-06-29-ugc-reel-share-design.md) (RU: `.ru.md`).

**Grounded seams (verified against current code):**
- `kernel/voice/tts_router.py:88` `generate_audio(text, language=None) -> (np.ndarray, int)`; `:150` `audio_to_wav_bytes(audio, sr) -> bytes`.
- `kernel/llm_router.py:33` `LLMRequest(text, context, available_tools, force_provider=None, system_prompt=None)`; `:106` `async route(req) -> LLMResponse(text, tool_calls, provider_used, latency_ms)`.
- `kernel/plugin_registry.py:229` `get(name) -> AgentManifest | None` (`.name`, `.description`).
- `kernel/main.py:2442` `GET /skills/{name}/export` — resolution (`SkillsRegistry.get(name).skill_dir` → `plugin_registry.skill_dir_for(name)`), name-gate `validate_frontmatter({"name": name, "description": "x"}, expected_name=name).valid`, honest `{"status":"error","message":...}` envelope.
- Tests: `tests/e2e/test_core_loop_build_deploy.py` (`@pytest.mark.core_loop`, `AsyncClient(ASGITransport(app))`, `_StubRouter`).

**Conventions (binding):** type hints on all signatures; Google-style docstrings on public funcs; no `print()` (use `logging`); specific exceptions; files ≤800 lines, funcs ≤50; no hardcoded paths/secrets. Run tests with `.venv\Scripts\python.exe -m pytest` (Vasily's box has no `make`).

---

## File Structure

| File | Responsibility |
|------|----------------|
| `kernel/reel/__init__.py` | Package marker; re-exports `generate_reel`. |
| `kernel/reel/intro.py` | `build_intro_line()` — LLM one-shot intro + deterministic template fallback. |
| `kernel/reel/audio.py` | `synthesize_voice_clip()` — TTS + float32/mono normalization. |
| `kernel/reel/compose.py` | `compose_reel()` — Pillow frames + PyAV/libopenh264 video + audio mux → MP4. |
| `kernel/reel/generator.py` | `generate_reel()` — orchestrator wiring intro→audio→compose; `resolve_agent_meta()`. |
| `kernel/main.py` | New `GET /skills/{name}/reel` route (near `:2442`). |
| `kernel/share_links.py` | `build_import_link(name, bundle)` — backend single-source of the `kali://import?n=&d=` format (mirrors `mobile/lib/core/share_config.dart`). |
| `mobile/lib/presentation/share_to_reels_screen.dart` | Fetch `/reel`, content-type branch, MP4→PNG→text fallback chain. |
| `scripts/build_installer_premium.bat` | Stage the Cisco `openh264` DLL into `premium_stage`. |
| `tests/reel/test_intro.py` | Unit: intro LLM path + template fallback. |
| `tests/reel/test_audio.py` | Unit: normalization (float32, mono downmix). |
| `tests/reel/test_compose.py` | Unit: real tiny encode → MP4 with 1 video + 1 audio stream. |
| `tests/reel/test_share_links.py` | Unit: `build_import_link` format + Cyrillic URL-encoding. |
| `tests/e2e/_reel_harness.py` | Sync `build_app_with_agent(tmp, name, description)` — direct agent-dir register (NOT the async builder replay). |
| `tests/e2e/test_core_loop_reel_share.py` | E2e: route success (mp4) + honest-fail + TTS-fail fallback. |
| `mobile/test/share_to_reels_test.dart` | Widget: mp4 share vs PNG fallback on `/reel` error. |

Split rationale: each reel sub-function is independently testable (intro / audio / compose), keeping `compose.py` — the only nontrivial-I/O unit — isolated so its real-encode test doesn't drag the others.

---

## Chunk 1: Backend reel generation + route

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml` (the `[project].dependencies` array)

- [ ] **Step 1: Add deps**

Add `av`, `Pillow`, and `qrcode[pil]` to the runtime dependencies (these run on the desktop/creator backend only).

```toml
# in [project].dependencies
"av>=12.0.0",
"Pillow>=10.0.0",
"qrcode[pil]>=7.4.0",
```

- [ ] **Step 2: Install + verify import**

Run: `.venv\Scripts\python.exe -m pip install "av>=12.0.0" "Pillow>=10.0.0" "qrcode[pil]>=7.4.0"`
Then: `.venv\Scripts\python.exe -c "import av, PIL, qrcode; print('libopenh264' in av.codecs_available or av.codec.Codec('libopenh264','w').name)"`
(`av.codecs_available` is a set of codec-name **strings** — do not iterate `.name`.)
Expected: prints `libopenh264` (confirms the LGPL-safe H.264 encoder is resolvable in this PyAV build). If it raises `UnknownCodecError`, STOP and surface to human — the wheel lacks openh264 and the distribution staging (Task 9) needs the Cisco DLL on PATH first.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(reel): add av/Pillow/qrcode deps for backend reel rendering"
```

---

### Task 2: `build_intro_line` — intro text with template fallback

**Files:**
- Create: `kernel/reel/__init__.py`
- Create: `kernel/reel/intro.py`
- Test: `tests/reel/test_intro.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/reel/test_intro.py
import pytest
from kernel.reel.intro import build_intro_line


class _StubResp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tool_calls = None
        self.provider_used = "stub"
        self.latency_ms = 0


class _OkRouter:
    async def route(self, request):  # noqa: ANN001
        assert "повар" in request.text  # description fed into the prompt
        return _StubResp("Привет! Я повар-помощник, подскажу рецепты.")


class _DeadRouter:
    async def route(self, request):  # noqa: ANN001
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_build_intro_line_uses_llm_text() -> None:
    line = await build_intro_line("chef", "повар-помощник", _OkRouter())
    assert line == "Привет! Я повар-помощник, подскажу рецепты."


@pytest.mark.asyncio
async def test_build_intro_line_falls_back_to_template_on_error() -> None:
    line = await build_intro_line("chef", "повар-помощник", _DeadRouter())
    assert "chef" in line and "повар-помощник" in line
    assert line  # never empty, never raises


@pytest.mark.asyncio
async def test_build_intro_line_template_on_empty_llm() -> None:
    class _EmptyRouter:
        async def route(self, request):  # noqa: ANN001
            return _StubResp("   ")

    line = await build_intro_line("chef", "повар-помощник", _EmptyRouter())
    assert "chef" in line  # blank LLM output → template
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_intro.py -v`
Expected: FAIL — `ModuleNotFoundError: kernel.reel`.

- [ ] **Step 3: Implement**

```python
# kernel/reel/__init__.py
"""Backend reel (9:16 voice-video) generation for the UGC share loop."""
from kernel.reel.generator import generate_reel  # noqa: F401
```

```python
# kernel/reel/intro.py
"""Build the short spoken intro line for an agent's share reel."""
import logging

from kernel.llm_router import LLMRequest

logger = logging.getLogger(__name__)

_SYSTEM = (
    "Ты пишешь ОДНУ короткую дружелюбную фразу-представление голосового агента "
    "для рекламного ролика. Только одно предложение на русском, без кавычек, "
    "без эмодзи, не длиннее 15 слов."
)


def _template(name: str, description: str) -> str:
    """Deterministic fallback line used when the LLM is unavailable."""
    desc = description.strip().rstrip(".")
    return f"Привет! Я {name}. {desc}." if desc else f"Привет! Я {name}."


async def build_intro_line(name: str, description: str, router: object) -> str:
    """Return a one-sentence RU intro for the agent, in its voice.

    Uses a single non-streaming LLM call; on ANY failure or empty output,
    returns a deterministic template built from ``name``/``description``.
    Never raises, never returns empty.

    Args:
        name: Agent display/slug name.
        description: Agent description.
        router: An object exposing ``async route(LLMRequest) -> resp.text``.
    """
    prompt = (
        f"Представь голосового агента по имени «{name}». "
        f"Что он умеет: {description}. Напиши фразу-представление."
    )
    try:
        resp = await router.route(  # type: ignore[attr-defined]
            LLMRequest(text=prompt, context=[], available_tools=[], system_prompt=_SYSTEM)
        )
        text = (resp.text or "").strip().strip('"').strip()
        if text:
            return text
    except Exception:  # noqa: BLE001 — any provider error degrades to template
        logger.warning("reel intro LLM failed; using template", exc_info=True)
    return _template(name, description)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_intro.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/reel/__init__.py kernel/reel/intro.py tests/reel/test_intro.py
git commit -m "feat(reel): intro-line generator with deterministic template fallback"
```

---

### Task 3: `synthesize_voice_clip` — TTS + normalization

**Files:**
- Create: `kernel/reel/audio.py`
- Test: `tests/reel/test_audio.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/reel/test_audio.py
import numpy as np

from kernel.reel import audio as reel_audio


def test_synthesize_normalizes_to_float32_mono(monkeypatch) -> None:
    # Provider returns stereo int16 — must come back float32 mono.
    fake = (np.zeros((100, 2), dtype=np.int16), 24000)
    monkeypatch.setattr(reel_audio, "generate_audio", lambda text, language=None: fake)
    clip, sr = reel_audio.synthesize_voice_clip("привет")
    assert clip.dtype == np.float32
    assert clip.ndim == 1
    assert sr == 24000


def test_synthesize_passes_mono_through(monkeypatch) -> None:
    fake = (np.ones(50, dtype=np.float32), 22050)
    monkeypatch.setattr(reel_audio, "generate_audio", lambda text, language=None: fake)
    clip, sr = reel_audio.synthesize_voice_clip("привет")
    assert clip.shape == (50,)
    assert sr == 22050
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_audio.py -v`
Expected: FAIL — `AttributeError`/`ImportError` (no `synthesize_voice_clip`).

- [ ] **Step 3: Implement**

```python
# kernel/reel/audio.py
"""Synthesize and normalize the agent voice clip for the reel."""
import numpy as np

from kernel.voice.tts_router import generate_audio


def synthesize_voice_clip(text: str) -> tuple[np.ndarray, int]:
    """Synthesize ``text`` via the active TTS provider, normalized.

    `generate_audio` only guarantees ``np.ndarray``; dtype/channel layout
    differs across F5 vs ElevenLabs. Normalize to float32 mono so the
    downstream waveform-envelope and audio-mux logic get a stable input.

    Returns:
        (float32 mono audio in [-1, 1], sample_rate).
    """
    audio, sr = generate_audio(text)
    arr = np.asarray(audio)
    if np.issubdtype(arr.dtype, np.integer):
        max_val = float(np.iinfo(arr.dtype).max) or 1.0
        arr = arr.astype(np.float32) / max_val
    else:
        arr = arr.astype(np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return np.ascontiguousarray(arr, dtype=np.float32), int(sr)
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_audio.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/reel/audio.py tests/reel/test_audio.py
git commit -m "feat(reel): voice-clip synthesis with float32/mono normalization"
```

---

### Task 4: `compose_reel` — Pillow frames + PyAV encode/mux → MP4

**Files:**
- Create: `kernel/reel/compose.py`
- Test: `tests/reel/test_compose.py`

> **This is the only nontrivial-encode unit.** The test runs a REAL encode on a tiny synthetic clip and probes the output — that is what forces the PyAV API to be correct. The reference implementation below is the proven structure; the executing agent iterates the exact PyAV calls until the probe passes (PyAV version drift is expected here).

- [ ] **Step 1: Write failing test**

```python
# tests/reel/test_compose.py
from pathlib import Path

import av
import numpy as np

from kernel.reel.compose import compose_reel


def _probe(path: Path) -> dict:
    with av.open(str(path)) as c:
        video = [s for s in c.streams if s.type == "video"]
        audio = [s for s in c.streams if s.type == "audio"]
        return {
            "video": len(video),
            "audio": len(audio),
            "vcodec": video[0].codec_context.name if video else None,
            "duration_s": float(c.duration) / av.time_base if c.duration else 0.0,
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
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_compose.py -v`
Expected: FAIL — no `compose_reel`.

- [ ] **Step 3: Implement (reference structure — iterate to green)**

```python
# kernel/reel/compose.py
"""Compose a 9:16 MP4 reel: animated card frames + the agent voice clip."""
import io
import logging
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import qrcode
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

_W, _H, _FPS = 720, 1280, 30
_VCODEC = "libopenh264"  # LGPL-safe H.264 (spec §3.1)
_TAIL_S = 1.2  # closing "scan to install" frame after the voice ends
_BG = (15, 15, 19)
_ACCENT = (120, 200, 255)
_WHITE = (245, 245, 245)


def _amplitude_envelope(audio: np.ndarray, n: int) -> np.ndarray:
    """Down-sample |audio| into ``n`` buckets in [0,1] for the waveform bars."""
    if audio.size == 0 or n <= 0:
        return np.zeros(max(n, 0), dtype=np.float32)
    mag = np.abs(audio)
    buckets = np.array_split(mag, n)
    env = np.array([float(b.max()) if b.size else 0.0 for b in buckets], dtype=np.float32)
    peak = float(env.max()) or 1.0
    return env / peak


def _qr_image(link: str, size: int) -> Image.Image:
    qr = qrcode.QRCode(border=2)
    qr.add_data(link)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((size, size))


def _render_frame(
    frame_idx: int, n_voice_frames: int, env: np.ndarray, *,
    title: str, subtitle: str, intro_text: str, qr: Image.Image,
) -> Image.Image:
    """Render one RGB frame. During voice: animated waveform + captions.
    During the tail: the 'scan to install' QR frame."""
    img = Image.new("RGB", (_W, _H), _BG)
    d = ImageDraw.Draw(img)
    d.text((48, 96), title, fill=_WHITE)
    d.text((48, 150), subtitle, fill=_ACCENT)
    if frame_idx < n_voice_frames:
        # waveform bars across the middle, pulsing with the envelope, swept by time
        bars = len(env)
        if bars:
            bw = (_W - 96) // bars
            t = frame_idx / max(n_voice_frames - 1, 1)
            for i, e in enumerate(env):
                pulse = e * (0.5 + 0.5 * np.sin(8 * np.pi * t + i))
                h = int(40 + pulse * 300)
                x = 48 + i * bw
                d.rectangle([x, _H // 2 - h // 2, x + bw - 4, _H // 2 + h // 2], fill=_ACCENT)
        d.text((48, _H - 220), intro_text, fill=_WHITE)
    else:
        img.paste(qr, ((_W - qr.width) // 2, _H // 2 - qr.height // 2))
        d.text((48, _H // 2 + qr.height // 2 + 24), "Сканируй, чтобы установить", fill=_WHITE)
    return img


def compose_reel(
    audio: np.ndarray, sr: int, *, title: str, subtitle: str,
    intro_text: str, link: str, out_path: Path,
) -> Path:
    """Render a 9:16 MP4 to ``out_path``: animated card over the voice clip,
    ending on a QR 'scan to install' frame. Raises on encode failure.

    Returns:
        ``out_path``.
    """
    duration_s = (audio.size / sr) + _TAIL_S if sr else _TAIL_S
    n_frames = max(int(duration_s * _FPS), 1)
    n_voice_frames = max(int((audio.size / sr) * _FPS), 1) if sr else 1
    env = _amplitude_envelope(audio, n=48)
    qr = _qr_image(link, size=380)

    with av.open(str(out_path), mode="w") as container:
        vstream = container.add_stream(_VCODEC, rate=_FPS)
        vstream.width, vstream.height, vstream.pix_fmt = _W, _H, "yuv420p"

        for i in range(n_frames):
            img = _render_frame(i, n_voice_frames, env, title=title,
                                subtitle=subtitle, intro_text=intro_text, qr=qr)
            vframe = av.VideoFrame.from_image(img)
            for packet in vstream.encode(vframe):
                container.mux(packet)
        for packet in vstream.encode():  # flush video
            container.mux(packet)

        # Audio: transcode the normalized clip to AAC via a WAV round-trip so
        # the resampler handles AAC's required frame size / planar-float layout.
        from kernel.voice.tts_router import audio_to_wav_bytes
        wav = io.BytesIO(audio_to_wav_bytes(audio, sr))
        astream = container.add_stream("aac", rate=sr)
        with av.open(wav, mode="r") as src:
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=sr)
            for aframe in src.decode(audio=0):
                aframe.pts = None
                for rframe in resampler.resample(aframe):
                    for packet in astream.encode(rframe):
                        container.mux(packet)
            for packet in astream.encode():  # flush audio
                container.mux(packet)
    return out_path
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_compose.py -v`
Expected: PASS. If the probe fails on stream count/codec, adjust the PyAV encode loop (common drift points: `add_stream` codec name, `VideoFrame.from_image` vs `from_ndarray`, resampler `.resample()` returning a list vs single frame). Do NOT relax the assertions — make the encode correct.

- [ ] **Step 5: Commit**

```bash
git add kernel/reel/compose.py tests/reel/test_compose.py
git commit -m "feat(reel): 9:16 MP4 compose (Pillow frames + PyAV/libopenh264 + audio mux)"
```

---

### Task 5: `generate_reel` orchestrator + agent-meta resolution

**Files:**
- Create: `kernel/reel/generator.py`
- Test: `tests/reel/test_generator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/reel/test_generator.py
from pathlib import Path

import av
import numpy as np
import pytest

from kernel.reel import generator as gen


class _StubResp:
    text = "Привет! Я chef."
    tool_calls = None
    provider_used = "stub"
    latency_ms = 0


class _Router:
    async def route(self, request):  # noqa: ANN001
        return _StubResp()


@pytest.mark.asyncio
async def test_generate_reel_end_to_end(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        gen, "synthesize_voice_clip",
        lambda text: ((0.1 * np.sin(np.linspace(0, 200, 24000))).astype(np.float32), 24000),
    )
    out = await gen.generate_reel(
        name="chef", description="повар-помощник",
        link="kali://import?n=chef&d=AAAA", router=_Router(), out_dir=tmp_path,
    )
    assert out.exists()
    with av.open(str(out)) as c:
        assert any(s.type == "video" for s in c.streams)
        assert any(s.type == "audio" for s in c.streams)
```

- [ ] **Step 2: Run to verify fail** → no `generate_reel`.

- [ ] **Step 3: Implement**

```python
# kernel/reel/generator.py
"""Orchestrate reel generation: intro line -> voice clip -> 9:16 MP4."""
import logging
from pathlib import Path

from kernel.reel.audio import synthesize_voice_clip
from kernel.reel.compose import compose_reel
from kernel.reel.intro import build_intro_line

logger = logging.getLogger(__name__)


async def generate_reel(
    *, name: str, description: str, link: str, router: object, out_dir: Path,
) -> Path:
    """Produce a share reel MP4 for ``name`` and return its path.

    Args:
        name: Agent slug/name (used as the card title).
        description: Agent description (used for the intro + subtitle).
        link: Self-contained import link baked into the closing QR frame.
        router: LLM router (``async route``) for the intro line.
        out_dir: Directory to write ``{name}.mp4`` into.
    """
    intro = await build_intro_line(name, description, router)
    audio, sr = synthesize_voice_clip(intro)
    out_path = out_dir / f"{name}.mp4"
    return compose_reel(
        audio, sr, title=name, subtitle=description,
        intro_text=intro, link=link, out_path=out_path,
    )
```

- [ ] **Step 4: Run to verify pass** → 1 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/reel/generator.py tests/reel/test_generator.py
git commit -m "feat(reel): generate_reel orchestrator"
```

---

### Task 6: `GET /skills/{name}/reel` route + e2e

**Files:**
- Modify: `kernel/main.py` (add the route immediately after `skills_export`, ~`:2489`)
- Test: `tests/e2e/test_core_loop_reel_share.py`

- [ ] **Step 0: Create `kernel/share_links.py` + its unit test FIRST** (the route imports it)

```python
# kernel/share_links.py
"""Backend single-source of the self-contained agent import-link format.
Mirrors mobile/lib/core/share_config.dart `customLink` (kali://import?n=&d=)."""
from urllib.parse import urlencode


def build_import_link(*, name: str, bundle: str) -> str:
    """Return `kali://import?n=<name>&d=<bundle>` with query-encoding."""
    return "kali://import?" + urlencode({"n": name, "d": bundle})
```

```python
# tests/reel/test_share_links.py
from urllib.parse import parse_qs, urlsplit
from kernel.share_links import build_import_link


def test_build_import_link_roundtrips_cyrillic_name() -> None:
    link = build_import_link(name="повар", bundle="AAAA")
    parts = urlsplit(link)
    assert parts.scheme == "kali" and parts.netloc == "import"
    q = parse_qs(parts.query)
    assert q["n"] == ["повар"] and q["d"] == ["AAAA"]
```

Run: `.venv\Scripts\python.exe -m pytest tests/reel/test_share_links.py -v` → PASS. Commit:
`git add kernel/share_links.py tests/reel/test_share_links.py && git commit -m "feat(reel): backend import-link helper"`

- [ ] **Step 1: Write failing e2e tests**

```python
# tests/e2e/test_core_loop_reel_share.py
import av
import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

# Reuse the project's app factory + a deployed-agent fixture exactly as
# test_core_loop_build_deploy.py does. See that file for `_build_app` / how a
# real agent is deployed into a tmp agents_dir; mirror it here.
from tests.e2e._reel_harness import build_app_with_agent  # NEW small helper (extract from build_deploy)


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_returns_mp4(tmp_path, monkeypatch) -> None:
    import kernel.reel.audio as reel_audio
    monkeypatch.setattr(
        reel_audio, "generate_audio",
        lambda text, language=None: ((0.1 * np.sin(np.linspace(0, 200, 24000))).astype(np.float32), 24000),
    )
    app = build_app_with_agent(tmp_path, name="chef", description="повар-помощник")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/chef/reel")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/mp4")
    assert len(r.content) > 0
    out = tmp_path / "got.mp4"
    out.write_bytes(r.content)
    with av.open(str(out)) as ct:
        assert any(s.type == "video" for s in ct.streams)
        assert any(s.type == "audio" for s in ct.streams)


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_honest_fail_unknown_agent(tmp_path) -> None:
    app = build_app_with_agent(tmp_path, name="chef", description="x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/no-such-agent/reel")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"


@pytest.mark.core_loop
@pytest.mark.asyncio
async def test_reel_route_falls_back_to_error_when_tts_dies(tmp_path, monkeypatch) -> None:
    import kernel.reel.audio as reel_audio

    def _boom(text, language=None):
        raise RuntimeError("no TTS engine")

    monkeypatch.setattr(reel_audio, "generate_audio", _boom)
    app = build_app_with_agent(tmp_path, name="chef", description="x")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/skills/chef/reel")
    assert r.status_code == 200
    assert r.json()["status"] == "error"  # honest error, not a crash
```

> `build_app_with_agent(tmp_path, name, description)` lives in NEW `tests/e2e/_reel_harness.py` and must be **synchronous and fast**: call `create_app()`, then register a hand-written agent dir directly onto `app.state.plugin_registry` (write a minimal `manifest.yaml`/`skill.yaml` under a tmp `agents_dir` and call `register_dir`, the same primitive Phase A uses) — do NOT replay the async `/builder/start → answer → deploy` HTTP flow (slow, and the helper is called synchronously in the tests). Reuse `create_app` + the agent-dir shape from `test_core_loop_build_deploy.py`; do not duplicate the builder flow.

- [ ] **Step 2: Run to verify fail** → 404/AttributeError (no route / no harness).

- [ ] **Step 3: Implement the route**

```python
# kernel/main.py — insert right after skills_export (≈ line 2489)
    @app.get("/skills/{name}/reel")
    async def skills_reel(name: str):
        """Render a 9:16 voice reel (MP4) for a created agent — the UGC share
        hook. Honest-fail JSON envelope on any error (mobile falls back to the
        PNG card). Mirrors /skills/{name}/export resolution + name gate."""
        import tempfile
        from pathlib import Path

        from starlette.background import BackgroundTask
        from fastapi.responses import FileResponse, JSONResponse

        from kernel.llm_router import LLMRouter
        from kernel.reel import generate_reel
        from kernel.share_links import build_import_link
        from kernel.skills.validator import validate_frontmatter

        # Resolve agent + description mirroring /export's two-tier lookup:
        # SkillsRegistry first (builtin/user SKILL.md), then the live plugin
        # registry (voice-built manifest.yaml agents — the primary share target).
        reg = _get_skills_registry()
        skill = reg.get(name)
        if skill is not None:
            description = skill.description
        else:
            manifest = app.state.plugin_registry.get(name)
            if manifest is None:
                return JSONResponse({"status": "error", "message": f"Agent '{name}' not found locally"})
            description = manifest.description
        if not validate_frontmatter({"name": name, "description": "x"}, expected_name=name).valid:
            return JSONResponse({
                "status": "error",
                "message": (
                    f"Agent name '{name}' can't be shared yet — names must be "
                    "lowercase latin letters, digits and single hyphens."
                ),
            })
        try:
            export = await skills_export(name)  # reuse the existing bundle builder
            if export.get("status") != "ok":
                return JSONResponse(export)
            link = build_import_link(name=name, bundle=export["data"])
            # LLMRouter is NOT on app.state — the chat path constructs it inline
            # from config (kernel/main.py:~1454). Mirror that here.
            router = LLMRouter(app.state.config_manager.config.llm)
            tmp = Path(tempfile.mkdtemp(prefix="kali_reel_"))
            out = await generate_reel(
                name=name, description=description, link=link,
                router=router, out_dir=tmp,
            )
            # Clean the temp dir after the response is streamed (no leak).
            import shutil
            return FileResponse(
                str(out), media_type="video/mp4", filename=f"{name}.mp4",
                background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
            )
        except Exception as exc:  # noqa: BLE001 — honest error, never 500 to the user
            logger.exception("reel render failed for %s", name)
            return JSONResponse({"status": "error", "message": f"Reel render failed: {exc}"})
```

> **Grounding sub-steps the agent must confirm before this compiles:**
> 1. `_get_skills_registry()` and `app.state.config_manager.config.llm` — both used by the existing `/export` and chat routes respectively; verify the exact names by grep in `kernel/main.py` (`_get_skills_registry`, `LLMRouter(`). Use whatever the chat path actually passes to `LLMRouter(...)`.
> 2. `kernel/share_links.py` does NOT exist yet — **create it** (it is required): a `build_import_link(*, name: str, bundle: str) -> str` returning `kali://import?n=<urlencoded name>&d=<bundle>`, the single backend source mirroring `mobile/lib/core/share_config.dart`'s `customLink`. Add `tests/reel/test_share_links.py` asserting the format + URL-encoding of a Cyrillic name. (Do this as Task 6 Step 0, before the route, so the import resolves.)
> 3. `PluginRegistry.get(name)` returns an `AgentManifest` with `.description` (used elsewhere in `kernel/main.py`); confirm by grep before relying on it.

- [ ] **Step 4: Run to verify pass**

Run: `.venv\Scripts\python.exe -m pytest tests/e2e/test_core_loop_reel_share.py -v`
Expected: 3 passed.

- [ ] **Step 5: Full gate**

Run: `.venv\Scripts\python.exe -m pytest -m core_loop -q`
Expected: previous 10 + new reel tests all pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add kernel/main.py tests/e2e/test_core_loop_reel_share.py tests/e2e/_reel_harness.py
git commit -m "feat(reel): GET /skills/{name}/reel route + core_loop e2e (mp4/honest-fail/fallback)"
```

---

## Chunk 2: Mobile integration + distribution

### Task 7: Mobile reel fetch + content-type branch + fallback chain

**Files:**
- Modify: `mobile/lib/presentation/share_to_reels_screen.dart`
- Modify: `mobile/lib/core/config.dart` or wherever `ServerConfig.api` lives (no change expected; reuse)
- Test: `mobile/test/share_to_reels_test.dart`

- [ ] **Step 1: Write failing widget test**

Mock the dio client so `GET /skills/{name}/reel` returns (a) `200 video/mp4` bytes and (b) `200 application/json {"status":"error"}`. Assert the share path uses the MP4 file in case (a) and falls back to the PNG-card path in case (b). Reuse the existing test harness style in `mobile/test/`.

- [ ] **Step 2: Run to verify fail.**

- [ ] **Step 3: Implement.** In `_prepare()`, after `_link` is set, fetch `/skills/{name}/reel` with `responseType: ResponseType.bytes`. Branch on `resp.headers.value('content-type')`:
  - starts with `video/mp4` → write bytes to a temp `kali_reel_<slug>.mp4`, store `_reelPath`.
  - otherwise (JSON / error / exception) → leave `_reelPath` null.
  In `_share()`, prefer `_reelPath` for `files:`, else the existing `_renderCardPng` PNG, else text+link. Add the "Собираю рил…" progress state reusing existing l10n keys. Keep the link/caption/QR untouched.

- [ ] **Step 4: Run to verify pass.**

Run: `flutter test test/share_to_reels_test.dart` (and `flutter analyze` clean).

- [ ] **Step 5: Commit**

```bash
git add mobile/lib/presentation/share_to_reels_screen.dart mobile/test/share_to_reels_test.dart
git commit -m "feat(reel): mobile fetches /reel mp4, content-type branch, PNG fallback"
```

---

### Task 8: Distribution — stage the openh264 codec

**Files:**
- Modify: `scripts/build_installer_premium.bat` (staging section, near the `robocopy /E` step)

- [ ] **Step 1: Add staging step.** Stage the Cisco `openh264` DLL (the one PyAV's libav loads for `libopenh264`) into `premium_stage` next to the other FFmpeg/libav DLLs, using `robocopy /E` (NOT `/MIR` — wipes `.hf_cache`). If Task 1 Step 2 showed `libopenh264` already resolvable from the PyAV wheel inside the frozen bundle, this step is a no-op verification instead — document which is the case in a comment.

- [ ] **Step 2: Verify.** Document the verification: a built backend can `import av` and instantiate `av.codec.Codec("libopenh264", "w")`. (Full live-verify happens in the consolidated rebuild pass, not here.)

- [ ] **Step 3: Commit**

```bash
git add scripts/build_installer_premium.bat
git commit -m "build(reel): stage openh264 codec into premium installer bundle"
```

---

## Final verification (before handoff to live-verify)

- [ ] `.venv\Scripts\python.exe -m pytest -m core_loop -q` → all green (10 prior + reel e2e).
- [ ] `.venv\Scripts\python.exe -m pytest tests/reel -q` → all green.
- [ ] `flutter analyze` (in `mobile/`) clean; `flutter test test/share_to_reels_test.dart` green.
- [ ] Commit any remaining + (by Vasily's word) push `main` for backup.
- [ ] Note in the session handoff: **installer rebuild required** for the reel to run live (carries `av`/openh264); the consolidated live-verify pass creates an agent by voice → shares → confirms a real MP4 with audible Jarvis voice.

---

## Out of scope (do NOT build here — tracked in spec §9)
Deferred-deep-link friend auto-import · «Сообщество» engagement depth · SKILL.md interop proof · KALI-Super-Context (separate cycle).
