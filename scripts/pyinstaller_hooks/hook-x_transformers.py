"""PyInstaller hook: collect x_transformers in SOURCE form.

F5-TTS jit-scripts ``softclamp`` (defined in ``x_transformers/attend.py``) via
``torch.jit.script``, which calls ``inspect.getsource()`` at runtime. PyInstaller's
default collection embeds modules as bytecode inside the PYZ archive, so
``getsource()`` fails in the frozen bundle with::

    Can't get source for <function softclamp>. TorchScript requires source access
    in order to carry out compilation, make sure original .py files are available.

Collecting x_transformers as source ('py') ships the ``.py`` on disk and makes
each module import from it (``co_filename`` -> the real ``.py``), so
``inspect.getsource()`` works. Root-caused 2026-06-06 (Premium v3 frozen F5 load).
"""

module_collection_mode = "py"
