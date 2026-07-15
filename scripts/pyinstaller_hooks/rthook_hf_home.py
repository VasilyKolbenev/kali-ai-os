"""Frozen-bundle fix: point HF_HOME at the BUNDLED ``.hf_cache`` before any import.

``huggingface_hub`` resolves its cache location ONCE, at import time, into
module-level constants (``huggingface_hub.constants.HF_HUB_CACHE``). Setting
``HF_HOME`` after that import has NO effect — the value is already frozen.

``kernel/voice/stt.py:98`` does ``os.environ.setdefault("HF_HOME", ...)`` inside
``load()``, which is far too late in the frozen app: the TTS prewarm imports
transformers -> huggingface_hub long before STT loads. So the bundled cache was
never consulted; hub used its default ``~/.cache/huggingface`` instead.

That went unnoticed until 2026-07-15 because the dev machine happened to have
the same Whisper model in its GLOBAL cache — the 1.0.0-rc1 frozen smoke passed
`whisper` by reading that, not the bundle. Once the global cache was gone the
truth surfaced: "Unable to open file 'model.bin' in model
'C:\\Users\\<user>\\.cache\\huggingface\\hub\\models--Systran--faster-whisper-small\\...'"
plus live HuggingFace HEAD requests. On a user's machine that means STT is dead
offline and silently re-downloads ~500 MB online — with a 461 MB model.bin
sitting unused inside the bundle.

Runtime hooks run BEFORE application imports, which is the only place this can
be fixed without patching third-party code.

``setdefault`` (not force): an explicit user/CI ``HF_HOME`` still wins, which is
what `scripts/frozen_smoke.py` and offline verification rely on.
"""
import os
import sys

# Only meaningful in a frozen bundle; in dev the repo-local .hf_cache that
# stt.py computes is already correct (nothing imports hub before the app there).
meipass = getattr(sys, "_MEIPASS", None)
if meipass:
    cache = os.path.join(meipass, ".hf_cache")
    if os.path.isdir(cache):
        os.environ.setdefault("HF_HOME", cache)
        # Windows symlink noise: the bundled cache ships materialized real
        # files (scripts/materialize_hf_symlinks.py), so the warning is moot.
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    else:
        # Loud, not swallowed: a missing bundled cache means every model falls
        # back to the network — exactly the failure this hook exists to prevent.
        print(
            f"[rthook_hf_home] WARNING: bundled cache not found at {cache} — "
            "models will resolve against the global HF cache / network",
            file=sys.stderr,
        )
