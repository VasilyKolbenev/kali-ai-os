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


# ── F3: mandatory stage-root XOR installed-root + manifest ──────────────────
def test_parse_args_requires_root_and_manifest() -> None:
    with pytest.raises(SystemExit):
        fs.parse_args(["--port", "3007"])  # no root, no manifest


def test_parse_args_stage_root_ok() -> None:
    ns = fs.parse_args(["--stage-root", "r", "--manifest", "m"])
    assert ns.stage_root == "r" and ns.manifest == "m"


def test_parse_args_installed_root_ok() -> None:
    ns = fs.parse_args(["--installed-root", "i", "--manifest", "m"])
    assert ns.installed_root == "i"


def test_parse_args_rejects_both_roots() -> None:
    with pytest.raises(SystemExit):
        fs.parse_args(["--stage-root", "r", "--installed-root", "i", "--manifest", "m"])


# ── F3: production-shaped manifest of the WHOLE stage/install root ───────────
def _sealed_stage_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "premium_stage"
    (root / "kali-backend" / "_internal").mkdir(parents=True)
    (root / "kali-backend" / "kali-backend.exe").write_bytes(b"BE")
    (root / "kali-backend" / "_internal" / "lib.zip").write_bytes(b"L")
    (root / "kali-desktop.exe").write_bytes(b"DT")
    (root / "models").mkdir()
    (root / "models" / "model.bin").write_bytes(b"W")
    (root / "install-webview2.ps1").write_bytes(b"PS")
    manifest = stage_policy.build_manifest(root, version="1.0.0-rc3", git_sha="a" * 40,
                                           mode="internal", receipts=[],
                                           asset_manifest_sha256="c" * 64)
    mpath = root / stage_policy.MANIFEST_NAME
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    return root, mpath


def test_verify_stage_root_matches_manifest_ok(tmp_path: Path) -> None:
    root, mpath = _sealed_stage_root(tmp_path)
    fs.verify_root_matches_manifest(root, mpath)  # whole root, not just the bundle


def test_verify_stage_root_detects_drift_outside_bundle(tmp_path: Path) -> None:
    # F3#10: a drift in a stage-owned file OUTSIDE kali-backend (models/) — which the
    # old bundle-only manifest missed — is now caught by the whole-root manifest.
    root, mpath = _sealed_stage_root(tmp_path)
    (root / "models" / "model.bin").write_bytes(b"TAMPERED")
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_root_matches_manifest(root, mpath)


def test_verify_installed_root_allows_inno_generated(tmp_path: Path) -> None:
    root, mpath = _sealed_stage_root(tmp_path)
    (root / "unins000.exe").write_bytes(b"UNINST")  # Inno-generated uninstaller
    (root / "unins000.dat").write_bytes(b"DAT")
    fs.verify_installed_root(root, mpath)  # allowlisted → ok


def test_verify_installed_root_rejects_unknown_extra(tmp_path: Path) -> None:
    root, mpath = _sealed_stage_root(tmp_path)
    (root / "stray.dll").write_bytes(b"X")  # neither manifest-owned nor Inno-generated
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_installed_root(root, mpath)


def test_verify_installed_root_rejects_nested_inno(tmp_path: Path) -> None:
    # G6: an Inno-named file is only tolerated at the ROOT; a nested one is a bypass.
    root, mpath = _sealed_stage_root(tmp_path)
    (root / "models" / "unins999.exe").write_bytes(b"NESTED")
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_installed_root(root, mpath)


def test_verify_installed_root_rejects_divergent_installed_manifest(tmp_path: Path) -> None:
    # G6: the shipped STAGE_MANIFEST must equal the passed manifest.
    root, mpath = _sealed_stage_root(tmp_path)
    other = tmp_path / "other.json"
    m = json.loads(mpath.read_text(encoding="utf-8")); m["version"] = "9.9.9"
    other.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_installed_root(root, other)


def test_verify_installed_root_requires_shipped_manifest(tmp_path: Path) -> None:
    # H2.4: инсталляция без собственного STAGE_MANIFEST.json больше не «проходит»
    root, mpath = _sealed_stage_root(tmp_path)
    passed = tmp_path / "passed-manifest.json"
    passed.write_bytes(mpath.read_bytes())
    mpath.unlink()  # установка без собственного STAGE_MANIFEST.json
    with pytest.raises(stage_policy.ManifestError) as exc:
        fs.verify_installed_root(root, passed)
    assert "STAGE_MANIFEST" in str(exc.value)


@pytest.mark.parametrize("name", ["unins.exe", "unins1.exe", "unins0000.dat",
                                  "unins000.txt", "Unins000.exe.bak"])
def test_verify_installed_root_rejects_non_inno_names(tmp_path: Path, name: str) -> None:
    # H2.5: allowlist — РОВНО unins<3 цифры>.exe/.dat в корне, ничего похожего
    root, mpath = _sealed_stage_root(tmp_path)
    (root / name).write_bytes(b"X")
    with pytest.raises(stage_policy.ManifestError):
        fs.verify_installed_root(root, mpath)


def test_verify_installed_root_requires_reparse_free(tmp_path: Path) -> None:
    import subprocess
    import sys as _sys
    if _sys.platform != "win32":
        pytest.skip("junctions are Windows-only")
    root, mpath = _sealed_stage_root(tmp_path)
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "j"), str(tmp_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip("mklink /J unavailable")
    with pytest.raises(stage_policy.ReparseError):
        fs.verify_installed_root(root, mpath)


def test_bundle_is_contained_under_root(tmp_path: Path) -> None:
    root, _ = _sealed_stage_root(tmp_path)
    bundle = fs.bundle_under_root(root)
    assert bundle == root / "kali-backend" and bundle.is_dir()


# ── F3: port-free, instance-id, version-vs-manifest (foreign listener guard) ─
def test_assert_port_free_ok_when_free() -> None:
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    fs.assert_port_free(port)  # nothing listening → ok


def test_assert_port_free_raises_when_occupied() -> None:
    import socket
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    port = s.getsockname()[1]
    try:
        with pytest.raises(fs.SmokeError):
            fs.assert_port_free(port)
    finally:
        s.close()


def test_check_health_ok() -> None:
    fs.check_health({"status": "ok", "version": "1.0.0-rc3", "desktop_instance_id": "ABC"},
                    expected_instance_id="ABC", manifest_version="1.0.0-rc3")


def test_check_health_foreign_instance_id_fails() -> None:
    # a foreign listener that doesn't echo OUR instance id must never count
    with pytest.raises(fs.SmokeError):
        fs.check_health({"version": "1.0.0-rc3", "desktop_instance_id": "OTHER"},
                        expected_instance_id="ABC", manifest_version="1.0.0-rc3")


def test_check_health_version_mismatch_fails() -> None:
    # version is compared to the manifest, not a dev-imported kernel
    with pytest.raises(fs.SmokeError):
        fs.check_health({"version": "9.9.9", "desktop_instance_id": "ABC"},
                        expected_instance_id="ABC", manifest_version="1.0.0-rc3")


def test_new_instance_id_is_unique_hex() -> None:
    a, b = fs.new_instance_id(), fs.new_instance_id()
    assert a != b and len(a) >= 16 and all(c in "0123456789abcdef" for c in a)


# ── G8: drain child output to log files (no undrained PIPE deadlock) ─────────
def test_tail_bounded(tmp_path: Path) -> None:
    p = tmp_path / "log.txt"
    p.write_bytes(b"A" * 10000)
    assert fs._tail(p, n_bytes=100) == "A" * 100


def test_tail_missing_file(tmp_path: Path) -> None:
    assert fs._tail(tmp_path / "nope.log") == ""


# ── H3.4: хвост читается seek-ом от конца, а не Path.read_bytes целиком ──────
class _CountingFile:
    """Обёртка файла, считающая, СКОЛЬКО байт реально прочитано."""

    def __init__(self, fh, counter: dict) -> None:
        self._fh = fh
        self._counter = counter

    def read(self, size: int = -1) -> bytes:
        data = self._fh.read(size)
        self._counter["read"] += len(data)
        return data

    def seek(self, *args) -> int:
        return self._fh.seek(*args)

    def tell(self) -> int:
        return self._fh.tell()

    def __enter__(self) -> _CountingFile:
        return self

    def __exit__(self, *exc) -> None:
        self._fh.close()


def test_tail_reads_only_the_last_bytes_of_a_huge_log(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "backend.err.log"
    size = 16 * 1024 * 1024  # 16 MiB: слурпать целиком ради 100 байт недопустимо
    with log.open("wb") as fh:
        fh.seek(size - 5)
        fh.write(b"TAILZ")
    counter = {"read": 0}
    real_open = Path.open

    def _counting_open(self: Path, *args, **kwargs):  # noqa: ANN202
        return _CountingFile(real_open(self, *args, **kwargs), counter)

    def _forbidden_read_bytes(self: Path) -> bytes:
        raise AssertionError("_tail must not slurp the whole log via Path.read_bytes")

    monkeypatch.setattr(Path, "open", _counting_open)
    monkeypatch.setattr(Path, "read_bytes", _forbidden_read_bytes)
    tail = fs._tail(log, n_bytes=100)
    assert tail.endswith("TAILZ") and len(tail) == 100
    assert counter["read"] <= 100, f"read {counter['read']} bytes for a 100-byte tail"


def test_main_does_not_use_undrained_pipe() -> None:
    src = Path(fs.__file__).read_text(encoding="utf-8")
    assert "stdout=subprocess.PIPE" not in src and "stderr=subprocess.PIPE" not in src


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
