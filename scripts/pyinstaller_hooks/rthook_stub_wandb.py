"""PyInstaller RUNTIME hook: stub out ``wandb`` before any app import.

``f5_tts/model/__init__.py`` imports the Trainer, whose ``trainer.py:9`` does an
unconditional ``import wandb`` (training-only). KALI only runs F5 INFERENCE and
never instantiates the Trainer, so wandb is never actually used. The real wandb
pulls vendored sub-deps (``wandb_gql``, ``wandb_graphql``, ``wandb_promise``)
that PyInstaller cannot bundle — they are registered in ``sys.modules`` during
``import wandb`` rather than being standalone packages, so static analysis,
``--collect-all`` and direct import all miss them.

Injecting a no-op stub into ``sys.modules`` at startup makes ``import wandb``
succeed instantly without touching the real (un-bundleable) package.
Root-caused 2026-06-06 (Premium v3 frozen F5 load, layered blocker chain).
"""
import importlib.machinery
import sys
import types


class _WandbStub(types.ModuleType):
    __version__ = "0.0.0+kali-stub"

    def __getattr__(self, name):
        # Dunders must NOT be answered with a lambda. In particular __file__ must be
        # ABSENT (AttributeError) so inspect.getmodule()/getsourcefile() — walked over
        # sys.modules by torch's custom-op registration during `import torch` — skips
        # this module instead of crashing on a non-string __file__ (PyInstaller
        # pyi_rth_inspect: "_path_normpath ... not function" → torch half-initialized).
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        # any real wandb.<x>(...) on a training path becomes a harmless no-op
        return lambda *args, **kwargs: None


_stub = _WandbStub("wandb")
# A valid __spec__ so importlib.util.find_spec("wandb") returns a spec instead of
# raising "ValueError: wandb.__spec__ is None" — transformers' optional wandb
# integration calls find_spec. With no bundled wandb metadata, transformers'
# is_wandb_available() then fails its version() check and skips wandb cleanly.
_stub.__spec__ = importlib.machinery.ModuleSpec("wandb", loader=None)
sys.modules["wandb"] = _stub
