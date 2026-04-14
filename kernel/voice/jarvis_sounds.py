"""JARVIS pre-recorded voice clips — play without TTS generation.

Categories:
- greet: startup/activation greeting (time-of-day aware)
- reply: wake word detected / ready to listen
- ok: command accepted/executed
- thanks: user said thanks
- stupid: unrecognized/silly request

Usage:
    from kernel.voice.jarvis_sounds import play_reaction
    play_reaction("ok")      # plays random ok1-ok4.mp3
    play_reaction("greet")   # plays time-appropriate greeting
"""

import logging
import random
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve sounds directory relative to project root
_SOUNDS_DIR = Path(__file__).parent.parent.parent / "resources" / "sounds"

REACTIONS: dict[str, list[str]] = {
    "greet": ["greet1"],
    "greet_morning": ["greet_morning"],
    "greet_day": ["greet_day"],
    "greet_evening": ["greet_evening"],
    "greet_night": ["greet_night"],
    "reply": ["reply1", "reply2", "reply3", "reply4", "reply5", "reply6"],
    "ok": ["ok1", "ok2", "ok3", "ok4"],
    "thanks": ["thanks"],
    "stupid": ["stupid"],
}


def _get_time_greeting() -> str:
    """Get appropriate greeting based on time of day."""
    hour = time.localtime().tm_hour
    if 5 <= hour < 12:
        return "greet_morning"
    elif 12 <= hour < 17:
        return "greet_day"
    elif 17 <= hour < 22:
        return "greet_evening"
    else:
        return "greet_night"


def play_reaction(reaction: str, lang: str = "ru") -> bool:
    """Play a pre-recorded JARVIS sound clip.

    Args:
        reaction: One of: greet, reply, ok, thanks, stupid
        lang: Language folder (ru, en)

    Returns:
        True if played successfully, False otherwise.
    """
    # Auto-select time-based greeting
    if reaction == "greet":
        reaction = _get_time_greeting()

    clips = REACTIONS.get(reaction, [])
    if not clips:
        logger.warning("No clips for reaction: %s", reaction)
        return False

    clip_name = random.choice(clips)
    clip_path = _SOUNDS_DIR / lang / f"{clip_name}.mp3"

    if not clip_path.exists():
        logger.warning("Sound file not found: %s", clip_path)
        return False

    try:
        import sounddevice as sd
        import soundfile as sf

        audio, sr = sf.read(str(clip_path))
        sd.play(audio, sr)
        sd.wait()
        logger.info("Played JARVIS reaction: %s (%s)", reaction, clip_name)
        return True
    except Exception as e:
        logger.warning("Failed to play sound %s: %s", clip_path, e)
        return False


def should_use_clip(response_text: str) -> str | None:
    """Determine if response should use a pre-recorded clip instead of TTS.

    Returns reaction name if a clip should be used, None for TTS generation.
    """
    text = response_text.lower().strip()

    # Short confirmations → "ok" clip
    ok_phrases = [
        "готово", "выполнено", "сделано", "принято", "понял", "хорошо",
        "ок", "ok", "done", "got it", "understood", "sure",
        "запущено", "остановлено", "установлено", "создано", "удалено",
    ]
    for phrase in ok_phrases:
        if text.startswith(phrase) or text == phrase:
            return "ok"

    # Greetings → time-based greeting clip
    greet_phrases = [
        "привет", "здравствуй", "добр", "hello", "hi ", "good morning",
        "good evening", "доброе утро", "добрый день", "добрый вечер",
    ]
    for phrase in greet_phrases:
        if text.startswith(phrase):
            return "greet"

    # Thanks
    if any(w in text for w in ["спасибо", "благодар", "thank"]):
        return "thanks"

    # Long responses → use TTS generation
    return None
