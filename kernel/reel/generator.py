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
