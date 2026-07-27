"""Build Premium backend — F5-TTS + CUDA torch for local GPU voice synthesis.

Target: ~4GB installer (includes torch+cu128, F5 model, FFmpeg DLLs).
For users with NVIDIA GPU (RTX 20+ series) who want fully offline JARVIS voice.

Distribution: Google Drive / Yandex.Disk link (too big for Telegram).
"""

import importlib.util as _ilu
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.release import asset_bootstrap as ab  # noqa: E402
from scripts.release import receipts as rc  # noqa: E402

ROOT = Path(__file__).parent.parent
ENTRY = ROOT / "kernel" / "entry.py"
DIST = ROOT / "dist_premium"
NAME = "kali-backend"

Runner = Callable[..., Any]


class BuildError(RuntimeError):
    """The backend build failed or did not produce its onedir (fail-closed)."""


def assert_build_output(returncode: int, out_dir: Path) -> None:
    """H1.5 — PyInstaller's exit code alone is not proof of a build.

    A zero exit with no onedir on disk (a wiped/redirected distpath, a spec that
    produced nothing) used to fall through silently and the wrapper exited 0."""
    if returncode != 0:
        raise BuildError(f"PYINSTALLER_FAILED: exit code {returncode}")
    if not out_dir.is_dir():
        raise BuildError(
            f"MISSING_OUTPUT: PyInstaller reported success but {out_dir} does not exist")


def lgpl_ffmpeg_dir() -> Path:
    """The ONE shipping source-of-truth for the LGPL FFmpeg DLLs (H1.2).

    Same directory the fetcher installs into and the composer stages, so the bytes
    swapped into av.libs cannot diverge from the bytes the installer ships."""
    return ab.sot_ffmpeg_dir(DIST)


def missing_lgpl_files(lgpl_dir: Path) -> list[str]:
    """The LGPL files the av.libs swap needs and does not have."""
    required = [f"{soname}.dll" for soname in _FFMPEG_SONAMES] + ["LICENSE.txt"]
    return [name for name in required if not (lgpl_dir / name).is_file()]


def assert_lgpl_set_available() -> None:
    """Preflight the av.libs swap BEFORE the build, not after it (H4/D2).

    dist_premium is gitignored, so on a fresh checkout the SoT is absent by default.
    Discovering that after a ~20-minute PyInstaller run costs the whole build and
    leaves an unusable onedir behind."""
    lgpl_dir = lgpl_ffmpeg_dir()
    missing = missing_lgpl_files(lgpl_dir)
    if missing:
        raise BuildError(
            f"LGPL_SET_MISSING: {lgpl_dir} lacks {missing}. Prepare the shipping "
            "source-of-truth first:\n"
            "  1) python -m scripts.release.asset_bootstrap\n"
            "  2) python scripts/fetch_lgpl_ffmpeg.py"
        )

DATAS = [
    (str(ROOT / "agents"), "agents"),
    (str(ROOT / "config"), "config"),
    (str(ROOT / "resources" / "sounds"), "resources/sounds"),
    # Vendored Cyrillic TrueType fonts for the reel renderer; must resolve at
    # Path(__file__).parent/"assets" inside the frozen bundle (kernel/reel/compose.py).
    (str(ROOT / "kernel" / "reel" / "assets" / "DejaVuSans.ttf"), "kernel/reel/assets"),
    (str(ROOT / "kernel" / "reel" / "assets" / "DejaVuSans-Bold.ttf"), "kernel/reel/assets"),
]

# torchcodec ships native libs (libtorchcodec_core/_custom_ops/_pybind_ops {4..8})
# that F5 loads at synth time via a FileFinder on the torchcodec package dir; they
# MUST land in _internal/torchcodec/. We locate them via find_spec (which does NOT
# execute torchcodec — `import torchcodec` raises when its FFmpeg DLL deps aren't on
# the path) and add each as data into the torchcodec/ subdir. This mirrors the dev
# env where torchcodec is fully present (and F5 still synthesizes — it tolerates a
# torchcodec that can't load and falls back to soundfile).
_tc_spec = _ilu.find_spec("torchcodec")
if _tc_spec is not None and _tc_spec.origin:
    _tc_dir = Path(_tc_spec.origin).parent
    for _lib in sorted(_tc_dir.glob("libtorchcodec_*.dll")) + sorted(
        _tc_dir.glob("libtorchcodec_*.pyd")
    ):
        DATAS.append((str(_lib), "torchcodec"))

HIDDEN = [
    "kernel.runtime_paths",
    "kernel.model_downloader",
    "kernel.jarvis_persona",
    "kernel.voice.tts_router",
    "kernel.voice.tts_engine_f5",
    "kernel.voice.tts_engine_elevenlabs",
    "kernel.voice.text_preprocessor",
    "kernel.voice.jarvis_sounds",
    "kernel.voice.pipeline",
    "kernel.voice.vad",
    "kernel.voice.stt",
    "kernel.voice.wake_word",
    "kernel.voice.recorder",
    "kernel.skill_executor",
    "kernel.skill_templates.tracker",
    "kernel.skill_templates.reminder",
    "kernel.skill_templates.monitor",
    "kernel.skill_templates.notifier",
    "kernel.skill_templates.logger",
    "kernel.sandbox.network_proxy",
    "kernel.sandbox.permission_enforcer",
    "kernel.sandbox.rate_limiter",
    "kernel.sandbox.backend",
    "kernel.sandbox.audit",
    "kernel.sandbox.http_client",
    "kernel.skills",
    "kernel.skills.loader",
    "kernel.skills.validator",
    "kernel.skills.registry",
    "kernel.skills.converter",
    "kernel.skills.catalog",
    "kernel.skills.installer",
    "kernel.skills.publisher",
    "kernel.builder.intent_classifier",
    "kernel.builder.safety_gate",
    "kernel.builder.skill_generator",
    "kernel.builder.agent_generator",
    "kernel.builder.deployer",
    "kernel.builder.wizard",
    "kernel.catalog.package",
    "kernel.catalog.client",
    "kernel.catalog.installer",
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "yaml",
    "croniter",
    "soundfile",
    "sounddevice",
    "openwakeword.model",
    "requests",
    # F5-TTS + torch CUDA stack
    "f5_tts",
    "f5_tts.api",
    "f5_tts.infer",
    "f5_tts.model",
    "vocos",
    "torch",
    "torchaudio",
    "torchaudio.compliance",
    "torchaudio.compliance.kaldi",
    "torchaudio.transforms",
    "torchcodec",
    "transformers",
    "huggingface_hub",
    "faster_whisper",
    "elevenlabs",
    "elevenlabs.client",
    "ruaccent",
    "onnxruntime",
]

# Packages whose runtime data files (e.g. bundled .onnx models, configs)
# must be collected into the PyInstaller bundle. Without these, packages
# look at <pkg>/resources/ at runtime and fail with NO_SUCHFILE.
#
# - openwakeword: ships 9 .onnx models (incl hey_jarvis, alexa, melspectrogram)
#   under openwakeword/resources/models/.
# - f5_tts / vocos: bundled configs + small data referenced by F5TTS().
# - ruaccent: Russian accent dictionary for TTS preprocessing.
# - faster_whisper: model assets used at first-run download path.
COLLECT_DATA = [
    "openwakeword",
    "f5_tts",
    "vocos",
    "ruaccent",
    "faster_whisper",
]

# Packages that need EVERYTHING — Python source + data + binaries. Required
# when the package uses lazy imports (`_LazyModule`) that PyInstaller's
# static analyzer can't detect at build time.
#
# - transformers: f5_tts.infer.utils_infer does `from transformers import
#   pipeline` at module level; transformers/__init__.py lazy-loads submodules
#   via _LazyModule which PyInstaller misses. Without --collect-all the v2
#   build crashed with ModuleNotFoundError on every F5 load attempt
#   (root cause caught 2026-05-18 during max-confidence debug session).
# - torch: heavy stack with submodules pulled lazily by transformers/f5_tts.
#   Belt-and-suspenders even though `torch` is in HIDDEN.
COLLECT_ALL = [
    "transformers",
    "torch",
    # NOTE: do NOT --collect-all torchcodec — PyInstaller would import it to analyze
    # submodules, and `import torchcodec` raises (its native libs need FFmpeg DLLs on
    # the path, absent at build time). torchcodec's .py + metadata come via HIDDEN +
    # COPY_METADATA; its native .pyd/.dll come via the explicit DATAS block below.
    #
    # UGC voice-reel rendering (kernel/reel/compose.py):
    # - av (PyAV): static analysis misses the bundled libav* native DLLs that
    #   carry the H.264 encoder. --collect-all ships them so the frozen backend's
    #   `import av` + libopenh264 encode works (LGPL-safe; no separate Cisco DLL
    #   staging needed — openh264 ships inside the PyAV wheel's binaries).
    # - PIL (Pillow): frame rasterization; --collect-all pulls its C-extension
    #   image plugins.
    # - qrcode: closing "scan to install" frame; its PIL image factory is a lazy
    #   import PyInstaller's static analyzer can miss.
    "av",
    "PIL",
    "qrcode",
    # ctranslate2 (faster-whisper backend): its package dir vendors
    # cudnn64_9.dll which plain collection missed — without it
    # `ctranslate2._ext` dies with "DLL load failed" in the frozen bundle
    # (second landmine behind the av one, 2026-07-13).
    "ctranslate2",
]


# FFmpeg sonames vendored by the PyAV 17 wheel (delvewheel-mangled in av.libs).
# The wheel's builds are GPL (--enable-gpl, hard-linked to libx264) — merely
# deleting libx264 breaks av._core AT IMPORT (root-caused 2026-07-13: the
# frozen Whisper/reel silently died since the June prune; never live-booted).
_FFMPEG_SONAMES = (
    "avcodec-62",
    "avdevice-62",
    "avfilter-11",
    "avformat-62",
    "avutil-60",
    "swresample-6",
    "swscale-9",
)


def swap_avlibs_to_lgpl(out_dir: Path) -> list[str]:
    """Replace PyAV's vendored GPL FFmpeg in av.libs with the LGPL build.

    KALI's proprietary installer must not ship GPL codecs, but PyAV wheels
    hard-link libx264 — so the GPL DLLs are *replaced*, not just pruned:

    1. delete the mangled GPL FFmpeg DLLs + libx264/libx265;
    2. copy the BtbN LGPL set (the premium_assets SoT, fetched by
       ``scripts/fetch_lgpl_ffmpeg.py``, soname-matched n8.1) in under their
       PLAIN names — FFmpeg's inter-DLL imports resolve there via the
       ``os.add_dll_directory(av.libs)`` delvewheel patch;
    3. ALSO copy each LGPL DLL under the exact delvewheel-mangled filename the
       wheel used — ``av/_core.pyd``'s import table references those literal
       names and cannot be re-pointed.

    The reel encoder keeps libopenh264 (BSD, still vendored); decode paths
    (faster-whisper, reel) run on the LGPL avcodec.

    Args:
        out_dir: The PyInstaller onedir output (contains ``_internal/av.libs``).

    Returns:
        Human-readable actions taken (empty if av.libs is absent).
    """
    av_libs = out_dir / "_internal" / "av.libs"
    if not av_libs.is_dir():
        return []
    lgpl_dir = lgpl_ffmpeg_dir()
    missing = missing_lgpl_files(lgpl_dir)
    if missing:
        raise SystemExit(
            f"LGPL FFmpeg set incomplete in {lgpl_dir} (missing {missing}) — "
            "run scripts/fetch_lgpl_ffmpeg.py first; shipping the GPL av.libs "
            "is not an option."
        )

    actions: list[str] = []
    # Map soname -> mangled filename before deleting anything.
    mangled: dict[str, str] = {}
    for dll in list(av_libs.iterdir()):
        low = dll.name.lower()
        if "x264" in low or "x265" in low:
            dll.unlink()
            actions.append(f"deleted {dll.name}")
            continue
        for soname in _FFMPEG_SONAMES:
            if low.startswith(f"{soname}-"):
                mangled[soname] = dll.name
                dll.unlink()
                actions.append(f"deleted GPL {dll.name}")

    for soname in _FFMPEG_SONAMES:
        src = lgpl_dir / f"{soname}.dll"
        shutil.copy2(src, av_libs / src.name)
        actions.append(f"LGPL {src.name}")
        if soname in mangled:
            shutil.copy2(src, av_libs / mangled[soname])
            actions.append(f"LGPL as {mangled[soname]}")
    shutil.copy2(lgpl_dir / "LICENSE.txt", av_libs / "FFMPEG-LGPL-LICENSE.txt")
    return actions


def main(*, runner: Runner = subprocess.run) -> int:
    try:
        assert_lgpl_set_available()  # H4/D2: refuse before the expensive build
    except BuildError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", NAME,
        "--onedir",  # NSIS-friendly for 3+ GB backend
        "--console",
        "--distpath", str(DIST),
        "--workpath", str(ROOT / "build" / "pyinstaller_premium"),
        "--specpath", str(ROOT / "build"),
        "--noconfirm",
        "--icon", str(ROOT / "src-tauri" / "icons" / "icon.ico"),
        # Custom hooks (e.g. x_transformers -> source mode for torch.jit.script).
        "--additional-hooks-dir", str(ROOT / "scripts" / "pyinstaller_hooks"),
        # Stub wandb at runtime (training-only dep pulled by f5_tts.model.trainer;
        # its vendored sub-deps wandb_gql/graphql/promise are un-bundleable).
        "--runtime-hook", str(ROOT / "scripts" / "pyinstaller_hooks" / "rthook_stub_wandb.py"),
        # transformers 5.x lazy-module loses `pipeline` under PyInstaller —
        # bind it eagerly before f5_tts imports (see the hook's docstring).
        "--runtime-hook", str(ROOT / "scripts" / "pyinstaller_hooks" / "rthook_transformers_pipeline.py"),
        # HF_HOME must point at the bundled .hf_cache BEFORE anything imports
        # huggingface_hub (it freezes the cache path at import time). Without
        # this the 461 MB bundled Whisper model is ignored and STT dies offline
        # / silently re-downloads — see the hook's docstring (rc1 hid this bug
        # because the dev machine's global cache happened to hold the model).
        "--runtime-hook", str(ROOT / "scripts" / "pyinstaller_hooks" / "rthook_hf_home.py"),
        "--exclude-module", "wandb",
    ]

    for src, dst in DATAS:
        cmd.extend(["--add-data", f"{src};{dst}"])
    for imp in HIDDEN:
        cmd.extend(["--hidden-import", imp])
    for pkg in COLLECT_DATA:
        cmd.extend(["--collect-data", pkg])
    for pkg in COLLECT_ALL:
        cmd.extend(["--collect-all", pkg])
    # Bundle dist-info METADATA for packages that transformers version-checks at
    # import time via importlib.metadata.version(). Code is bundled (HIDDEN) but
    # without the metadata version() raises PackageNotFoundError and aborts the
    # whole transformers.pipelines import (root-caused 2026-06-06: torchcodec,
    # checked unconditionally in transformers/audio_utils.py:55).
    for pkg in ("torchcodec",):
        cmd.extend(["--copy-metadata", pkg])

    cmd.append(str(ENTRY))

    # G2: HEAD + clean-state captured BEFORE the build; the receipt (written only on
    # success, below) re-checks HEAD didn't move and derives dirty from git itself.
    # H6-3: a dirty worktree refuses HERE — never burn a multi-GB build that can never
    # earn a receipt, and never let a mid-build `git stash` launder it clean.
    head_before, clean_before = rc.capture_head_state(ROOT)
    if not clean_before:
        print("ERROR: DIRTY_AT_START: the worktree is dirty — build from a clean "
              "dedicated worktree (a dirty build can never earn a BUILD_RECEIPT)",
              file=sys.stderr)
        return 1

    print(f"Building Premium {NAME} (F5 + CUDA torch)...")
    result = runner(cmd, cwd=str(ROOT))

    out_dir = DIST / NAME
    try:
        assert_build_output(result.returncode, out_dir)
    except BuildError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1
    # Swap PyAV's vendored GPL FFmpeg for the LGPL build (deleting alone breaks
    # av._core — see swap_avlibs_to_lgpl docstring).
    actions = swap_avlibs_to_lgpl(out_dir)
    print(f"av.libs LGPL swap: {len(actions)} actions")
    total = sum(f.stat().st_size for f in out_dir.rglob("*") if f.is_file())
    print(f"\nSuccess! Built Premium backend at {out_dir}")
    print(f"Size: {total / 1024 / 1024 / 1024:.2f} GB uncompressed")
    # BUILD_RECEIPT — real build-time provenance (toolchain from actual cmds).
    try:
        toolchain = rc.collect_toolchain([
            ("python", [sys.executable, "--version"]),
            ("pyinstaller", [sys.executable, "-m", "PyInstaller", "--version"]),
        ])
    except rc.ReceiptError as e:
        print(f"ERROR: {e}", file=sys.stderr)  # fail-closed: no receipt without a toolchain
        return 1
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    receipt_path = DIST / f"{NAME}.BUILD_RECEIPT.json"
    rc.finalize_build_receipt(out_dir, receipt_path, repo=ROOT, version=version,
                              build_kind="pyinstaller-onedir", toolchain=toolchain,
                              head_before=head_before, clean_before=clean_before)
    print(f"BUILD_RECEIPT written: {receipt_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
