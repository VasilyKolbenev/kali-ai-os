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
import json
import subprocess
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
    """Готовый ЗАПЕЧАТАННЫЙ premium_assets SoT с полным LGPL-набором."""
    from scripts.release import asset_bootstrap as _ab
    from scripts.release import stage_policy
    lgpl = dist / "premium_assets" / "models" / "ffmpeg"
    lgpl.mkdir(parents=True)
    for soname in _BB._FFMPEG_SONAMES:
        (lgpl / f"{soname}.dll").write_bytes(b"LGPL")
    (lgpl / "LICENSE.txt").write_text("LESSER GENERAL PUBLIC LICENSE", encoding="utf-8")
    sot, manifest = _ab.sot_paths(dist)  # H7-4: билд читает запечатанный снимок
    _ab.write_manifest_atomic(manifest, {"entries": stage_policy.file_content_hashes(sot)})
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


def test_backend_swap_refuses_dlls_that_drifted_from_the_snapshot(monkeypatch,
                                                                  tmp_path: Path) -> None:
    # H7-4: копируем ровно то, что пинит снимок, — иначе SoT подменили под сборкой
    from scripts.release import asset_bootstrap as _ab
    dist = tmp_path / "dist_premium"
    lgpl = _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "DIST", dist)
    _sot, manifest = _ab.sot_paths(dist)
    snapshot = _ab.load_asset_snapshot(manifest)
    (lgpl / f"{_BB._FFMPEG_SONAMES[0]}.dll").write_bytes(b"SWAPPED-UNDER-THE-BUILD")
    out = tmp_path / "bundle"
    (out / "_internal" / "av.libs").mkdir(parents=True)
    (out / "_internal" / "av.libs" / "x.dll").write_bytes(b"X")
    with pytest.raises(SystemExit) as exc:
        _BB.swap_avlibs_to_lgpl(out, snapshot=snapshot)
    assert "LGPL_SET_DRIFTED" in str(exc.value)


def test_backend_build_holds_the_asset_lock(monkeypatch, tmp_path: Path) -> None:
    # H7-4: сборка обязана читать SoT под общим замком — иначе fetcher подменит DLL
    from scripts.release import asset_bootstrap as _ab
    dist = tmp_path / "dist_premium"
    _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "DIST", dist)
    _pretend_clean(monkeypatch, _BB)
    runner = _Runner(returncode=0)
    with _ab.asset_lock(dist):  # замок уже держит кто-то другой
        assert _BB.main(runner=runner) == 1
    assert runner.calls == [], "сборка не должна стартовать без замка на ассеты"


def test_backend_assert_snapshot_covers_lgpl_set(monkeypatch, tmp_path: Path) -> None:
    from scripts.release import asset_bootstrap as _ab
    dist = tmp_path / "dist_premium"
    _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "DIST", dist)
    _sot, manifest = _ab.sot_paths(dist)
    snapshot = _ab.load_asset_snapshot(manifest)
    _BB.assert_snapshot_covers_lgpl_set(snapshot)  # не поднимает
    thin = _ab.AssetSnapshot(digest="a" * 64, entries={"ffmpeg/LICENSE.txt": "b" * 64})
    with pytest.raises(_BB.BuildError) as exc:
        _BB.assert_snapshot_covers_lgpl_set(thin)
    assert "LGPL_SET_UNPINNED" in str(exc.value)


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


# ── F3: сборка, испачкавшая дерево, обязана быть nonzero и БЕЗ receipt ──────
def _repo_for_wrapper(tmp_path: Path) -> Path:
    """Настоящий git-репозиторий: VERSION, один tracked-файл, игнор артефактов."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "t@t"), ("config", "user.name", "T"),
                 ("config", "commit.gpgsign", "false"), ("config", "core.autocrlf", "false")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    (repo / "VERSION").write_text("1.0.0-rc3", encoding="utf-8")
    (repo / "generated.txt").write_text("committed", encoding="utf-8")
    (repo / ".gitignore").write_text("dist_premium/\ntarget/\n", encoding="utf-8")
    for args in (("add", "-A"), ("commit", "-m", "seed")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


class _DirtyingRunner(_Runner):
    """Сборка УДАЛАСЬ (артефакт есть), но попутно переписала tracked-файл.

    Ровно то, что делает `tsc -b` с ui/tsconfig.tsbuildinfo и tauri со схемами."""

    def __init__(self, artifact: Path, repo: Path, *, as_dir: bool = False) -> None:
        super().__init__(returncode=0)
        self._artifact, self._repo, self._as_dir = artifact, repo, as_dir

    def __call__(self, cmd, **kwargs):  # noqa: ANN001, ANN003
        if self._as_dir:
            self._artifact.mkdir(parents=True, exist_ok=True)
            (self._artifact / "kali-backend.exe").write_bytes(b"EXE")
        else:
            self._artifact.parent.mkdir(parents=True, exist_ok=True)
            self._artifact.write_bytes(b"EXE")
        (self._repo / "generated.txt").write_text("rewritten by the build", encoding="utf-8")
        return super().__call__(cmd, **kwargs)


def test_desktop_wrapper_nonzero_when_the_build_dirties_a_tracked_file(
        monkeypatch, tmp_path: Path) -> None:
    repo = _repo_for_wrapper(tmp_path)
    exe = repo / "target" / "release" / "kali-desktop.exe"
    monkeypatch.setattr(bd, "ROOT", repo)
    monkeypatch.setattr(bd, "EXE", exe)
    monkeypatch.setattr(bd.rc, "collect_toolchain", lambda cmds: "cargo=x; rustc=y; tauri=z")
    runner = _DirtyingRunner(exe, repo)
    assert bd.main(runner=runner, which=lambda n: "npm.cmd") == 1
    assert runner.calls, "сборка обязана была стартовать — иначе проверяется не тот инвариант"
    assert exe.is_file(), "EXE создан: отказ именно из-за грязного дерева, не из-за сборки"
    assert not exe.with_name(exe.name + ".BUILD_RECEIPT.json").exists()


def test_desktop_wrapper_writes_clean_receipt_when_nothing_is_dirtied(
        monkeypatch, tmp_path: Path) -> None:
    repo = _repo_for_wrapper(tmp_path)
    exe = repo / "target" / "release" / "kali-desktop.exe"
    monkeypatch.setattr(bd, "ROOT", repo)
    monkeypatch.setattr(bd, "EXE", exe)
    monkeypatch.setattr(bd.rc, "collect_toolchain", lambda cmds: "cargo=x; rustc=y; tauri=z")

    class _CleanRunner(_Runner):
        def __call__(self, cmd, **kwargs):  # noqa: ANN001, ANN003
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"EXE")
            return super().__call__(cmd, **kwargs)

    assert bd.main(runner=_CleanRunner(), which=lambda n: "npm.cmd") == 0
    receipt = json.loads(exe.with_name(exe.name + ".BUILD_RECEIPT.json")
                         .read_text(encoding="utf-8"))
    assert receipt["dirty"] is False and receipt["version"] == "1.0.0-rc3"


def test_backend_wrapper_nonzero_when_the_build_dirties_a_tracked_file(
        monkeypatch, tmp_path: Path) -> None:
    # Радиус F3.1: finalize_build_receipt теперь поднимает и в backend-обёртке —
    # она обязана вернуть nonzero, а не выбросить traceback.
    repo = _repo_for_wrapper(tmp_path)
    dist = repo / "dist_premium"
    _sot_with_lgpl_set(dist)
    monkeypatch.setattr(_BB, "ROOT", repo)
    monkeypatch.setattr(_BB, "DIST", dist)
    monkeypatch.setattr(_BB.rc, "collect_toolchain", lambda cmds: "python=x; pyinstaller=y")
    runner = _DirtyingRunner(dist / _BB.NAME, repo, as_dir=True)
    assert _BB.main(runner=runner) == 1
    assert runner.calls, "сборка обязана была стартовать"
    assert (dist / _BB.NAME).is_dir(), "onedir создан: отказ из-за грязного дерева"
    assert not (dist / f"{_BB.NAME}.BUILD_RECEIPT.json").exists()


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
