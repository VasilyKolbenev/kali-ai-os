"""Tests for the LGPL FFmpeg swap step of the Premium backend build.

2026-07-13: the old delete-only prune_gpl_codecs BROKE the frozen bundle —
PyAV's avcodec hard-links libx264, so GPL DLLs must be REPLACED with the
LGPL set (plain + delvewheel-mangled names), not merely deleted.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_backend_premium",
    Path(__file__).resolve().parents[2] / "scripts" / "build_backend_premium.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
swap_avlibs_to_lgpl = _MOD.swap_avlibs_to_lgpl
_FFMPEG_SONAMES = _MOD._FFMPEG_SONAMES


@pytest.fixture
def lgpl_dir(tmp_path: Path, monkeypatch) -> Path:
    """A fake models/ffmpeg with the full LGPL soname set + license."""
    lgpl = tmp_path / "models" / "ffmpeg"
    lgpl.mkdir(parents=True)
    for soname in _FFMPEG_SONAMES:
        (lgpl / f"{soname}.dll").write_bytes(b"LGPL")
    (lgpl / "LICENSE.txt").write_text("LESSER GENERAL PUBLIC LICENSE")
    monkeypatch.setattr(_MOD, "ROOT", tmp_path)
    return lgpl


def _make_bundle(tmp_path: Path) -> Path:
    """A fake onedir output with delvewheel-mangled GPL av.libs."""
    av_libs = tmp_path / "bundle" / "_internal" / "av.libs"
    av_libs.mkdir(parents=True)
    for soname in _FFMPEG_SONAMES:
        (av_libs / f"{soname}-deadbeef00.dll").write_bytes(b"GPL")
    for extra in ("libopenh264-7-cafe.dll", "libdav1d-beef.dll",
                  "libx264-165-feed.dll", "libx265-f00d.dll"):
        (av_libs / extra).write_bytes(b"\x00")
    return tmp_path / "bundle"


def test_swap_replaces_gpl_with_lgpl_under_both_names(tmp_path, lgpl_dir) -> None:
    out_dir = _make_bundle(tmp_path)
    av_libs = out_dir / "_internal" / "av.libs"

    swap_avlibs_to_lgpl(out_dir)

    remaining = {p.name for p in av_libs.iterdir()}
    # x264/x265 gone
    assert not any("x264" in n or "x265" in n for n in remaining)
    # LGPL set present under BOTH plain and the original mangled names
    for soname in _FFMPEG_SONAMES:
        assert f"{soname}.dll" in remaining
        assert f"{soname}-deadbeef00.dll" in remaining
        assert (av_libs / f"{soname}-deadbeef00.dll").read_bytes() == b"LGPL"
    # non-FFmpeg vendored codecs untouched; license shipped
    assert "libopenh264-7-cafe.dll" in remaining
    assert "libdav1d-beef.dll" in remaining
    assert "FFMPEG-LGPL-LICENSE.txt" in remaining


def test_swap_noop_without_av_libs(tmp_path, lgpl_dir) -> None:
    """A build with no av.libs swaps nothing and does not raise."""
    (tmp_path / "empty").mkdir()
    assert swap_avlibs_to_lgpl(tmp_path / "empty") == []


def test_swap_refuses_when_lgpl_set_incomplete(tmp_path, lgpl_dir) -> None:
    """Shipping the GPL av.libs is never an option — missing LGPL set aborts."""
    (lgpl_dir / f"{_FFMPEG_SONAMES[0]}.dll").unlink()
    out_dir = _make_bundle(tmp_path)
    with pytest.raises(SystemExit):
        swap_avlibs_to_lgpl(out_dir)
