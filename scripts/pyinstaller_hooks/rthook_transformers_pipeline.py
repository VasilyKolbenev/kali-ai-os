"""Frozen-bundle fix: eagerly bind ``transformers.pipeline`` (v5 lazy break).

transformers 5.x resolves top-level names through ``_LazyModule`` +
``define_import_structure`` which SCANS the package directory at import time —
under PyInstaller that resolution loses the ``pipeline`` entry and
``from transformers import pipeline`` (f5_tts.infer.utils_infer:28) dies with
"cannot import name 'pipeline'", killing every F5 load (root-caused
2026-07-13 on the 1.0.0-rc1 frozen smoke; the venv import works).

``from X import Y`` falls back to ``getattr(X, 'Y')`` — so pre-binding the
attribute here (runtime hooks run before application imports) repairs the
name for the whole process without touching third-party code. Failure is
printed loudly instead of swallowed: a broken bind means F5 is dead anyway,
and the traceback in the boot log is the diagnostic we need.
"""
import traceback

try:
    import transformers

    try:
        _ = transformers.pipeline  # noqa: B018 — probe the lazy attr
    except Exception:
        from transformers.pipelines import pipeline as _pipeline

        transformers.pipeline = _pipeline
        print("[rthook] transformers.pipeline bound eagerly (v5 lazy fix)")
except Exception:
    print("[rthook] transformers.pipeline bind FAILED:")
    traceback.print_exc()
