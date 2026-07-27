"""TDD (red-first) для build-wrappers — H1 (fix-loop по 3-му Codex NO-GO).

Оба wrapper'а обязаны быть ИСПОЛНИМЫМИ и fail-closed БЕЗ multi-GB билда:

* desktop запускает ТОЧНУЮ команду ``npm --prefix ui exec -- tauri build
  --no-bundle`` через разрешённый npm-лаунчер (npm.cmd на Windows), без
  implicit shell-bypass (``shell=True``);
* backend возвращает nonzero, если PyInstaller соврал (rc=0, а onedir нет);
* сбор toolchain fail-closed: nonzero / unavailable / пустой вывод обязательной
  команды запрещает receipt (иначе provenance врёт «tauri=unavailable»).

Никаких реальных билдов: runner и резолвер npm инъектируются.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_desktop_premium as bd
from scripts.release import receipts as rc

ROOT = Path(__file__).resolve().parents[2]

_SPEC = importlib.util.spec_from_file_location(
    "build_backend_premium_h1", ROOT / "scripts" / "build_backend_premium.py")
_BB = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_BB)


def _pretend_clean(monkeypatch, module) -> None:  # noqa: ANN001
    """Реальное дерево репозитория грязное (pre-existing dirty), а эти тесты про
    другое — фиксируем clean-at-start, иначе они зеленеют не по той причине."""
    monkeypatch.setattr(module.rc, "capture_head_state", lambda repo: ("a" * 40, True))


class _Runner:
    """Инъектируемый subprocess.run: записывает вызовы, отдаёт заданный rc."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, cmd, **kwargs):  # noqa: ANN001, ANN003
        self.calls.append((list(cmd), dict(kwargs)))
        return SimpleNamespace(returncode=self.returncode, stdout="", stderr="")


# ── H1.3: точная команда сборки desktop + разрешение npm без shell ───────────
def test_desktop_build_command_is_exact_with_no_bundle() -> None:
    assert bd.build_command("C:/tools/npm.cmd") == [
        "C:/tools/npm.cmd", "--prefix", "ui", "exec", "--", "tauri", "build", "--no-bundle",
    ]


def test_desktop_resolve_npm_uses_launcher_from_which() -> None:
    resolved = bd.resolve_npm(which=lambda name: r"C:\Program Files\nodejs\npm.cmd")
    assert resolved.lower().endswith("npm.cmd")


def test_desktop_resolve_npm_fail_closed_when_absent() -> None:
    with pytest.raises(bd.BuildError) as exc:
        bd.resolve_npm(which=lambda name: None)
    assert "NPM_MISSING" in str(exc.value)


def test_desktop_main_runs_exact_command_without_shell(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bd, "EXE", tmp_path / "kali-desktop.exe")  # не появится → rc=1
    _pretend_clean(monkeypatch, bd)
    runner = _Runner(returncode=0)
    assert bd.main(runner=runner, which=lambda n: "npm.cmd") == 1
    cmd, kwargs = runner.calls[0]
    assert cmd == ["npm.cmd", "--prefix", "ui", "exec", "--", "tauri", "build", "--no-bundle"]
    assert kwargs.get("shell", False) is False  # никакого implicit shell-bypass


def test_desktop_main_fail_closed_without_npm(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bd, "EXE", tmp_path / "kali-desktop.exe")
    runner = _Runner(returncode=0)
    assert bd.main(runner=runner, which=lambda n: None) == 1
    assert runner.calls == []  # отказ ДО запуска сборки


def test_desktop_main_nonzero_when_build_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(bd, "EXE", tmp_path / "kali-desktop.exe")
    _pretend_clean(monkeypatch, bd)
    runner = _Runner(returncode=2)
    assert bd.main(runner=runner, which=lambda n: "npm.cmd") == 1
    assert runner.calls, "билд обязан был стартовать — иначе проверяется не тот инвариант"


# ── H1.5: backend rc=0 без onedir обязан быть nonzero ────────────────────────
def test_backend_assert_output_rejects_rc0_without_onedir(tmp_path: Path) -> None:
    with pytest.raises(_BB.BuildError) as exc:
        _BB.assert_build_output(0, tmp_path / "kali-backend")
    assert "MISSING_OUTPUT" in str(exc.value)


def test_backend_assert_output_rejects_nonzero(tmp_path: Path) -> None:
    out = tmp_path / "kali-backend"
    out.mkdir()
    with pytest.raises(_BB.BuildError) as exc:
        _BB.assert_build_output(3, out)
    assert "PYINSTALLER_FAILED" in str(exc.value)


def test_backend_assert_output_accepts_real_onedir(tmp_path: Path) -> None:
    out = tmp_path / "kali-backend"
    out.mkdir()
    _BB.assert_build_output(0, out)  # не поднимает


def _sot_with_lgpl_set(dist: Path) -> Path:
    """Готовый premium_assets SoT с полным LGPL-набором (предусловие билда)."""
    lgpl = dist / "premium_assets" / "models" / "ffmpeg"
    lgpl.mkdir(parents=True)
    for soname in _BB._FFMPEG_SONAMES:
        (lgpl / f"{soname}.dll").write_bytes(b"LGPL")
    (lgpl / "LICENSE.txt").write_text("LESSER GENERAL PUBLIC LICENSE", encoding="utf-8")
    return lgpl


def test_backend_main_nonzero_when_pyinstaller_lies(monkeypatch, tmp_path: Path) -> None:
    # PyInstaller вернул 0, но dist_premium/kali-backend не создан → билд провален.
    dist = tmp_path / "dist_premium"
    _sot_with_lgpl_set(dist)  # preflight должен пройти, иначе тест зелёный не по той причине
    monkeypatch.setattr(_BB, "DIST", dist)
    _pretend_clean(monkeypatch, _BB)
    runner = _Runner(returncode=0)
    assert _BB.main(runner=runner) == 1
    assert runner.calls, "билд обязан был запуститься — иначе проверяется не тот инвариант"


# ── H4/D2: предусловие LGPL-набора проверяется ДО многочасового билда ────────
def test_backend_preflight_refuses_missing_lgpl_set_before_building(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_BB, "DIST", tmp_path / "dist_premium")  # SoT отсутствует
    runner = _Runner(returncode=0)
    assert _BB.main(runner=runner) == 1
    assert runner.calls == [], "PyInstaller не должен был запуститься"


def test_backend_assert_lgpl_set_names_the_bootstrap_step(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(_BB, "DIST", tmp_path / "dist_premium")
    with pytest.raises(_BB.BuildError) as exc:
        _BB.assert_lgpl_set_available()
    message = str(exc.value)
    assert "asset_bootstrap" in message and "fetch_lgpl_ffmpeg" in message


def test_backend_assert_lgpl_set_accepts_complete_sot(monkeypatch, tmp_path: Path) -> None:
    dist = tmp_path / "dist_premium"
    _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "DIST", dist)
    _BB.assert_lgpl_set_available()  # не поднимает


# ── H6-3: dirty-at-start обязан отказать ДО запуска сборки ──────────────────
def test_backend_refuses_dirty_worktree_before_running(monkeypatch, tmp_path: Path) -> None:
    dist = tmp_path / "dist_premium"
    _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "DIST", dist)
    monkeypatch.setattr(_BB.rc, "capture_head_state", lambda repo: ("a" * 40, False))
    runner = _Runner(returncode=0)
    assert _BB.main(runner=runner) == 1
    assert runner.calls == [], "сборка не должна была стартовать на грязном дереве"
    assert not (dist / "kali-backend.BUILD_RECEIPT.json").exists()


def test_desktop_refuses_dirty_worktree_before_running(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "kali-desktop.exe"
    monkeypatch.setattr(bd, "EXE", exe)
    monkeypatch.setattr(bd.rc, "capture_head_state", lambda repo: ("a" * 40, False))
    runner = _Runner(returncode=0)
    assert bd.main(runner=runner, which=lambda n: "npm.cmd") == 1
    assert runner.calls == []
    assert not exe.with_name(exe.name + ".BUILD_RECEIPT.json").exists()


# ── H1.4: toolchain fail-closed (иначе receipt врёт про сборочную среду) ─────
def test_collect_toolchain_fail_closed_on_nonzero() -> None:
    with pytest.raises(rc.ReceiptError) as exc:
        rc.collect_toolchain([("tauri", [sys.executable, "-c", "import sys; sys.exit(3)"])])
    assert "TOOLCHAIN_FAILED" in str(exc.value)


def test_collect_toolchain_fail_closed_when_unavailable() -> None:
    with pytest.raises(rc.ReceiptError) as exc:
        rc.collect_toolchain([("tauri", ["kali-no-such-binary-h1", "--version"])])
    assert "TOOLCHAIN_UNAVAILABLE" in str(exc.value)


def test_collect_toolchain_fail_closed_on_empty_output() -> None:
    with pytest.raises(rc.ReceiptError) as exc:
        rc.collect_toolchain([("tauri", [sys.executable, "-c", "pass"])])
    assert "TOOLCHAIN_UNKNOWN" in str(exc.value)


def test_collect_toolchain_ok_records_real_version() -> None:
    tc = rc.collect_toolchain([("python", [sys.executable, "--version"])])
    assert tc.startswith("python=") and "Python" in tc


# ── H1.2: одна правда для LGPL FFmpeg — premium_assets SoT ───────────────────
def test_backend_lgpl_dir_is_the_premium_assets_sot() -> None:
    assert _BB.lgpl_ffmpeg_dir() == _BB.DIST / "premium_assets" / "models" / "ffmpeg"


def test_backend_does_not_read_repo_models_ffmpeg() -> None:
    src = (ROOT / "scripts" / "build_backend_premium.py").read_text(encoding="utf-8")
    assert 'ROOT / "models" / "ffmpeg"' not in src  # две правды устранены
