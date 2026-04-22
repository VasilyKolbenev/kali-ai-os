# Share-to-Reels — Plan Stub

> Status: STUB. Написан 2026-04-22. Full detail пишется после templates-gallery-v2.

**Goal:** Встроенная механика UGC — после deploy агента кнопка "Записать reel" захватывает screen + voice → готовое видео 9:16 / 1:1 для TikTok/Reels/Shorts.

**Depends on:** voice-builder-pilot + templates-gallery-v2 (нужна критическая масса use cases, иначе шарить особо нечего).

## Why now (trigger)

Distribution thesis KALI = UGC loop: create → reel → friends install. Без встроенного share-recorder'а K-factor остаётся 0.1–0.3. Это математический блокер.

## Scope

**In:**
1. Screen capture (Windows Graphics Capture API → macOS ScreenCaptureKit в след. фазе)
2. Audio overlay — user voice + JARVIS voice синхронизированные
3. Compose video — 9:16 и 1:1 варианты с KALI watermark (ненавязчивый)
4. Auto-caption — "Смотри что я сделал за Xсек в KALI" с подстановкой user's agent name
5. Save to disk + copy-to-clipboard + "Open in TikTok/Instagram" deeplinks
6. Анонимайзер — blur sensitive fields (API keys, file paths) автоматом

**Out:**
- Direct posting через API (требует OAuth на каждую платформу, огромный scope)
- Editing внутри KALI (trim, effects) — пусть user редактирует в native apps
- Audio music overlay (copyright minefield)

## Tech approach

**Windows:** [Windows.Graphics.Capture](https://learn.microsoft.com/en-us/windows/uwp/audio-video-camera/screen-capture) через Python winrt bindings или CSharp interop.
**MP4 encode:** ffmpeg (уже есть в models/ffmpeg/) через subprocess или python-ffmpeg.
**Format:** H.264 + AAC, ~15 Mbps target, 30fps, 1080×1920 (9:16) и 1080×1080 (1:1).

## Key UX moments

1. После deploy агента в UI → кнопка "Записать reel" (prominent)
2. Клик → 3-sec countdown → запись 15–60 сек
3. Stop → превью с waveform → confirm
4. Save → toast "Сохранено в Видео/KALI-Reels/" + button "Открыть папку"

## Risks

- **Windows capture API подводные камни:** разрешения, DPI awareness, multi-monitor — всё ломает edge cases. Нужен real-device тест.
- **Производительность:** 60fps capture + encode может съесть CPU. Throttle до 30fps, hardware encoder (NVENC) если есть GPU.
- **Privacy:** user не должен случайно записать пароли. Blur/redact heuristics нужны.

## Estimate

4–5 дней на Windows MVP (capture + encode + UI flow). macOS — отдельная неделя.

## Success metric

Первые 5 reels от real users в публичных сетях (not founder's demo). Когда пошли organic reels — UGC loop работает.
