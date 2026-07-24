"""TDD (red-first) для C6 OPUS-103 — cache-isolated offline-env smoke + SLA.

Тестируем ЧИСТЫЕ функции frozen_smoke: env-изоляция кэшей + offline-флаги +
external-HTTP block, обязательные --bundle/--manifest, manifest-match, /live SLA.
Реальный self-launch frozen bundle = live acceptance (не unit).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import frozen_smoke as fs
from scripts.release import stage_policy

_CACHE_VARS = ("HF_HOME", "HUGGINGFACE_HUB_CACHE", "TRANSFORMERS_CACHE",
               "TORCH_HOME", "XDG_CACHE_HOME")
_OFFLINE_FLAGS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")


# ── offline env: cache isolation ────────────────────────────────────────────
def test_offline_env_isolates_all_caches(tmp_path: Path) -> None:
    env = fs.build_offline_env(cache_root=tmp_path / "iso", base={"PATH": "/x"})
    for var in _CACHE_VARS:
        assert var in env
        assert str(tmp_path / "iso") in env[var]  # isolated, NOT the global cache


def test_offline_env_sets_offline_flags(tmp_path: Path) -> None:
    env = fs.build_offline_env(cache_root=tmp_path / "iso", base={})
    for flag in _OFFLINE_FLAGS:
        assert env[flag] == "1"


def test_offline_env_blocks_external_http_keeps_localhost(tmp_path: Path) -> None:
    env = fs.build_offline_env(cache_root=tmp_path / "iso", base={})
    assert env.get("HTTP_PROXY") and env.get("HTTPS_PROXY")   # external → dead sink
    assert "127.0.0.1" in env.get("NO_PROXY", "")             # localhost bypasses
    assert "localhost" in env.get("NO_PROXY", "")


def test_assert_offline_env_rejects_incomplete(tmp_path: Path) -> None:
    env = fs.build_offline_env(cache_root=tmp_path / "iso", base={})
    del env["HF_HOME"]  # a hole in the isolation
    with pytest.raises(fs.SmokeError):
        fs.assert_offline_env(env)


def test_assert_offline_env_accepts_complete(tmp_path: Path) -> None:
    env = fs.build_offline_env(cache_root=tmp_path / "iso", base={})
    fs.assert_offline_env(env)  # не поднимает


# ── mandatory --bundle / --manifest ─────────────────────────────────────────
def test_parse_args_requires_bundle_and_manifest() -> None:
    with pytest.raises(SystemExit):
        fs.parse_args(["--port", "3007"])  # ни bundle, ни manifest


def test_parse_args_ok_with_bundle_and_manifest() -> None:
    ns = fs.parse_args(["--bundle", "b", "--manifest", "m"])
    assert ns.bundle == "b" and ns.manifest == "m"


# ── bundle content must match its STAGE_MANIFEST ────────────────────────────
def _sealed_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "kali-backend"
    (bundle / "_internal").mkdir(parents=True)
    (bundle / "kali-backend.exe").write_bytes(b"BE")
    (bundle / "_internal" / "lib.zip").write_bytes(b"L")
    manifest = stage_policy.build_manifest(bundle, version="1.0.0-rc3",
                                           git_sha="s", mode="internal", receipts=[])
    mpath = tmp_path / "STAGE_MANIFEST.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return bundle, mpath


def test_bundle_manifest_match_ok(tmp_path: Path) -> None:
    bundle, mpath = _sealed_bundle(tmp_path)
    fs.verify_bundle_matches_manifest(bundle, mpath)  # не поднимает


def test_bundle_manifest_mismatch_fails(tmp_path: Path) -> None:
    bundle, mpath = _sealed_bundle(tmp_path)
    (bundle / "kali-backend.exe").write_bytes(b"DRIFTED")  # bundle разошёлся
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_bundle_matches_manifest(bundle, mpath)


# ── /live SLA: t0 → first HTTP 200 /live ≤ 1.0s ─────────────────────────────
def test_measure_sla_ok_under_deadline() -> None:
    clock = iter([0.0, 0.3])
    elapsed, latency = fs.measure_live_sla(
        poller=lambda: (200, 0.02), deadline_s=1.0,
        clock=lambda: next(clock), sleep=lambda s: None,
    )
    assert elapsed == pytest.approx(0.3) and latency == pytest.approx(0.02)


def test_measure_sla_raises_when_first_200_exceeds_deadline() -> None:
    clock = iter([0.0, 1.5])
    with pytest.raises(fs.SmokeError) as exc:
        fs.measure_live_sla(poller=lambda: (200, 0.1), deadline_s=1.0,
                            clock=lambda: next(clock), sleep=lambda s: None)
    assert "SLA" in str(exc.value)


def test_measure_sla_raises_when_never_ready() -> None:
    seq = iter([0.0, 0.5, 1.2])
    with pytest.raises(fs.SmokeError) as exc:
        fs.measure_live_sla(poller=lambda: (503, 0.0), deadline_s=1.0,
                            clock=lambda: next(seq), sleep=lambda s: None)
    assert "SLA" in str(exc.value)
