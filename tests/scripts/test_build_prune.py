"""Tests for the GPL-codec prune step of the Premium backend build."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_backend_premium",
    Path(__file__).resolve().parents[2] / "scripts" / "build_backend_premium.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
prune_gpl_codecs = _MOD.prune_gpl_codecs


def test_prune_removes_gpl_keeps_lgpl(tmp_path: Path) -> None:
    """libx264/libx265 are removed; libopenh264 + LGPL codecs are kept."""
    av_libs = tmp_path / "_internal" / "av.libs"
    av_libs.mkdir(parents=True)
    keep = ["libopenh264-7.dll", "avcodec-62.dll", "libvpx-9.dll", "libdav1d-7.dll"]
    drop = ["libx264-164.dll", "libx265-209.dll"]
    for name in keep + drop:
        (av_libs / name).write_bytes(b"\x00")

    removed = prune_gpl_codecs(tmp_path)

    assert sorted(removed) == sorted(drop)
    remaining = {p.name for p in av_libs.iterdir()}
    assert remaining == set(keep)


def test_prune_noop_without_av_libs(tmp_path: Path) -> None:
    """A build with no av.libs prunes nothing and does not raise."""
    assert prune_gpl_codecs(tmp_path) == []
