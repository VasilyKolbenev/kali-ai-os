"""TDD (red-first) для scripts/release/version.py — единый version source-of-truth.

Модуль ещё не написан → `ver`-фикстура импортит его лениво: сегодня все тесты
падают (ModuleNotFoundError), что и требуется. Стиль фикстур совпадает с
tests/scripts/test_publish_release.py (tmp_path-репо, точечные возмущения).
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import scripts.publish_release as pr

import _guard_fixtures as fx


@pytest.fixture
def ver():
    """Ленивый импорт: scripts/release/version.py не существует → red сегодня."""
    return importlib.import_module("scripts.release.version")


# ── 1. clean-checkout regression: check() работает на fixture, не на workspace ─
# Codex review: НЕ фиксируем временный skew реального репо вечным тестом (он
# исчезнет после sync и зависит от локального dirty Cargo.lock). Все version-
# тесты — на tmp fixture, независимы от рабочего дерева.
def test_check_passes_on_synced_fixture(ver, tmp_path: Path) -> None:
    """Полностью synced fixture → check() возвращает канонический VERSION."""
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, (fx.VERSION + "\n").encode("utf-8"))
    assert ver.check(tmp_path) == fx.VERSION


def test_check_detects_skew_on_fixture(ver, tmp_path: Path) -> None:
    """Skewed fixture → check() падает VERSION_SKEW (без чтения реального репо)."""
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, (fx.VERSION + "\n").encode("utf-8"))
    fx.write_pyproject(tmp_path, "1.0.0-rc1")   # уводим один источник
    with pytest.raises(SystemExit) as exc:
        ver.check(tmp_path)
    assert "VERSION_SKEW" in str(exc.value)


# ── 2. Cargo.lock: только блок kali-desktop, не формат и не dep ─────────────
def test_check_reads_kalidesktop_lock_version_not_format_or_deps(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    # kali-desktop=rc3, decoy foo=rc2, формат `version = 4`
    fx.write_cargo_lock(tmp_path, fx.VERSION, decoy_ver="1.0.0-rc2")
    got = ver.read_desktop_versions(tmp_path)["cargo_lock"]
    assert got == fx.VERSION          # блок kali-desktop
    assert got != "4"                 # не формат-хедер
    assert got != "1.0.0-rc2"         # не decoy-dep


# ── 3. sync правит только версию kali-desktop в Cargo.lock ──────────────────
def test_sync_only_rewrites_kalidesktop_lock_block(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, "1.0.0-rc2")
    fx.write_cargo_lock(tmp_path, "1.0.0-rc2", decoy_ver="1.0.0-rc2")
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")

    ver.sync(tmp_path)
    lock = (tmp_path / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    assert "\nversion = 4\n" in lock                     # формат-хедер нетронут
    assert 'version = "1.0.0-rc3"' in lock               # kali-desktop обновлён
    assert lock.count("1.0.0-rc2") == 1                  # остался только foo-dep
    assert 'version = "1.0.86"' in lock                  # anyhow нетронут

    after_first = (tmp_path / "src-tauri" / "Cargo.lock").read_bytes()
    ver.sync(tmp_path)                                   # идемпотентность
    assert (tmp_path / "src-tauri" / "Cargo.lock").read_bytes() == after_first


# ── 4. VERSION: BOM/CRLF/empty/multiline/невалидный semver ──────────────────
def test_version_file_bom_crlf_ok(ver, tmp_path: Path) -> None:
    fx.write_version_file(tmp_path, b"\xef\xbb\xbf1.0.0-rc3\r\n")
    assert ver.read_version_file(tmp_path) == "1.0.0-rc3"


@pytest.mark.parametrize("raw", [b"", b"1.0.0\n2.0.0\n", b"not-semver\n"])
def test_version_file_invalid_rejected(ver, tmp_path: Path, raw: bytes) -> None:
    fx.write_version_file(tmp_path, raw)
    with pytest.raises(SystemExit) as exc:
        ver.read_version_file(tmp_path)
    assert "VERSION_INVALID" in str(exc.value)


# ── 5. per-source расхождение — check называет источник ─────────────────────
@pytest.mark.parametrize("source", list(fx.DESKTOP_KEYS))
def test_check_per_source_divergence_parametrized(ver, tmp_path: Path, source: str) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")
    _diverge(tmp_path, source, "9.9.9")
    with pytest.raises(SystemExit) as exc:
        ver.check(tmp_path)
    msg = str(exc.value)
    assert "VERSION_SKEW" in msg
    assert source in msg          # назван конкретный источник


def _diverge(repo: Path, source: str, wrong: str) -> None:
    if source == "pyproject":
        fx.write_pyproject(repo, wrong)
    elif source == "kernel":
        fx.write_kernel(repo, wrong)
    elif source == "cargo_toml":
        fx.write_cargo_toml(repo, wrong)
    elif source == "cargo_lock":
        fx.write_cargo_lock(repo, wrong)
    elif source == "tauri":
        fx.write_tauri(repo, wrong)
    elif source == "iss":
        fx.write_iss(repo, wrong)
    elif source == "ui":
        fx.write_ui(repo, wrong)


# ── 6. sync стягивает 7 разных неверных значений к VERSION ──────────────────
def test_sync_writes_all_seven_distinct_wrong_values(ver, tmp_path: Path) -> None:
    fx.write_pyproject(tmp_path, "0.1.0")
    fx.write_kernel(tmp_path, "0.2.0")
    fx.write_cargo_toml(tmp_path, "0.3.0")
    fx.write_cargo_lock(tmp_path, "0.4.0")
    fx.write_tauri(tmp_path, "0.5.0")
    fx.write_iss(tmp_path, "0.6.0")
    fx.write_ui(tmp_path, "0.7.0")
    fx.write_pubspec(tmp_path)                  # sync завершает check() → нужен pubspec
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")

    ver.sync(tmp_path)
    got = ver.read_desktop_versions(tmp_path)   # per-file, не через check
    assert got == {k: fx.VERSION for k in fx.DESKTOP_KEYS}


# ── 6b. sync: отсутствующий anchor → VERSION_SYNC_FAILED, не ложный success ──
def _break_anchor(repo: Path, source: str) -> None:
    if source == "pyproject":
        fx.write_pyproject(repo, fx.VERSION, dynamic=True)          # нет [project].version
    elif source == "cargo_toml":
        (repo / "src-tauri").mkdir(exist_ok=True)
        (repo / "src-tauri" / "Cargo.toml").write_text(
            '[package]\nname = "kali-desktop"\n', encoding="utf-8")  # нет version
    elif source == "cargo_lock":
        (repo / "src-tauri").mkdir(exist_ok=True)
        (repo / "src-tauri" / "Cargo.lock").write_text(
            'version = 4\n\n[[package]]\nname = "foo"\nversion = "1.0"\n',
            encoding="utf-8")                                        # нет kali-desktop
    elif source == "tauri":
        (repo / "src-tauri").mkdir(exist_ok=True)
        (repo / "src-tauri" / "tauri.conf.json").write_text(
            '{"productName": "KALI"}', encoding="utf-8")            # нет version
    elif source == "kernel":
        fx.write_kernel(repo, None, style="missing")               # нет __version__
    elif source == "iss":
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / "installer_premium.iss").write_text(
            "[Setup]\nAppName=KALI\n", encoding="utf-8")            # нет #define AppVersion
    elif source == "ui":
        (repo / "ui").mkdir(exist_ok=True)
        (repo / "ui" / "package.json").write_text(
            '{\n  "name": "kali-ui"\n}\n', encoding="utf-8")        # нет top-level version


@pytest.mark.parametrize("source", list(fx.DESKTOP_KEYS))
def test_sync_fails_loud_on_missing_anchor(ver, tmp_path: Path, source: str) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, (fx.VERSION + "\n").encode("utf-8"))
    _break_anchor(tmp_path, source)
    with pytest.raises(SystemExit) as exc:
        ver.sync(tmp_path)
    assert "VERSION_SYNC_FAILED" in str(exc.value)


# ── 7. sync обновляет ВСЕ вхождения версии в .iss (не только #define) ────────
def test_sync_updates_all_iss_version_occurrences(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, "1.0.0-rc2")   # stale rc2 в header/Output/#define
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")

    ver.sync(tmp_path)
    iss = (tmp_path / "scripts" / "installer_premium.iss").read_text(encoding="utf-8")
    assert "1.0.0-rc2" not in iss                       # ни одного stale-вхождения
    assert ver.read_desktop_versions(tmp_path)["iss"] == fx.VERSION  # читает #define


# ── 8. kernel: варианты синтаксиса __version__ + hard-fail ──────────────────
@pytest.mark.parametrize("style,expected", [
    ("double", "1.0.0-rc3"),
    ("single", "1.0.0-rc3"),
    ("annotated", "1.0.0-rc3"),
    ("missing", None),
])
def test_kernel_version_parse_variants_and_hard_fail(
    ver, tmp_path: Path, style: str, expected: str | None
) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_kernel(tmp_path, fx.VERSION, style=style)
    if expected is None:
        with pytest.raises(SystemExit) as exc:
            ver.read_desktop_versions(tmp_path)
        assert "kernel" in str(exc.value)
    else:
        assert ver.read_desktop_versions(tmp_path)["kernel"] == expected


# ── 9. pyproject: [project].version через tomllib; dynamic → fail ───────────
def test_pyproject_tomllib_project_table(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_pyproject(tmp_path, fx.VERSION, decoy=True)   # decoy [tool.decoy] 9.9.9
    assert ver.read_desktop_versions(tmp_path)["pyproject"] == fx.VERSION


def test_pyproject_dynamic_version_hard_fails(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_pyproject(tmp_path, fx.VERSION, dynamic=True)  # dynamic=["version"]
    with pytest.raises(SystemExit) as exc:
        ver.read_desktop_versions(tmp_path)
    assert "pyproject" in str(exc.value)


# ── 10. pubspec: только top-level version; строгий X.Y.Z+N ──────────────────
def test_pubspec_top_level_only(ver, tmp_path: Path) -> None:
    fx.write_pubspec(tmp_path, "0.1.0+1", decoy=True)   # decoy version: под deps
    assert ver.read_mobile_version(tmp_path) == "0.1.0+1"


@pytest.mark.parametrize("bad", ["0.1.0", "0.1.0+", "0.1.0+abc"])
def test_pubspec_invalid_format_rejected(ver, tmp_path: Path, bad: str) -> None:
    fx.write_pubspec(tmp_path, bad)
    with pytest.raises(SystemExit) as exc:
        ver.read_mobile_version(tmp_path)
    assert "MOBILE_VERSION_INVALID" in str(exc.value)


# ── 10b. ui/package.json: только top-level version; sync без переформатирования ─
def test_ui_reads_top_level_version(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_ui(tmp_path, fx.VERSION, decoy=True)   # вложенный "engines".version 9.9.9
    assert ver.read_desktop_versions(tmp_path)["ui"] == fx.VERSION


@pytest.mark.parametrize("body", [
    '{\n  "name": "kali-ui"\n}\n',                  # top-level version отсутствует
    '{\n  "name": "kali-ui",\n  "version": 123\n}\n',  # version не строка
])
def test_ui_missing_or_nonstring_version_hard_fails(ver, tmp_path: Path, body: str) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    (tmp_path / "ui" / "package.json").write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ver.read_desktop_versions(tmp_path)
    assert "ui" in str(exc.value)


def test_sync_ui_updates_only_top_level_and_preserves_formatting(ver, tmp_path: Path) -> None:
    """sync правит только top-level version; вложенный decoy и остальной JSON целы."""
    fx.write_all_desktop(tmp_path, "1.0.0-rc2")
    fx.write_ui(tmp_path, "1.0.0-rc2", decoy=True)   # вложенный "engines".version 9.9.9
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")
    before = (tmp_path / "ui" / "package.json").read_text(encoding="utf-8")

    ver.sync(tmp_path)
    after = (tmp_path / "ui" / "package.json").read_text(encoding="utf-8")

    assert ver.read_desktop_versions(tmp_path)["ui"] == fx.VERSION  # top-level → rc3
    assert '"version": "9.9.9"' in after                # вложенный decoy НЕ тронут
    assert '"1.0.0-rc2"' not in after                   # stale top-level убран
    # структурно: изменилась ровно одна строка (top-level version), формат сохранён
    diff = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert diff == [('  "version": "1.0.0-rc2",', '  "version": "1.0.0-rc3",')]

    after_first = (tmp_path / "ui" / "package.json").read_bytes()
    ver.sync(tmp_path)                                   # идемпотентность
    assert (tmp_path / "ui" / "package.json").read_bytes() == after_first


# ── 11. manifest: реальный git SHA + dirty + component-map ──────────────────
def test_manifest_has_real_git_sha_dirty_and_component_map(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, b"1.0.0-rc3\n")
    fx.init_git(tmp_path)
    fx.commit_all(tmp_path, "init")

    m = ver.build_manifest(tmp_path)
    assert set(m) >= {"version", "git_sha", "git_sha_short", "dirty",
                      "components", "generated_at"}
    assert m["version"] == ver.read_version_file(tmp_path) == fx.VERSION
    assert m["git_sha"] == fx.head_sha(tmp_path)
    assert m["git_sha"].startswith(m["git_sha_short"])
    assert m["dirty"] is False
    assert m["components"] == {
        **ver.read_desktop_versions(tmp_path),
        "mobile": ver.read_mobile_version(tmp_path),
    }

    # грязное дерево → dirty True (значение версии не меняем)
    (tmp_path / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nname = "kali-desktop"\nversion = "1.0.0-rc3"\n# touched\n',
        encoding="utf-8",
    )
    assert ver.build_manifest(tmp_path)["dirty"] is True


# ── 12. semver: rc<N> сравнивается ЧИСЛЕННО (rc10 > rc2, не лексически) ──────
def test_compare_semver_ranks_rc_numerically(ver) -> None:
    assert ver.compare_semver("1.0.0-rc10", "1.0.0-rc2") == 1
    assert ver.compare_semver("1.0.0-rc2", "1.0.0-rc10") == -1
    # регресс-страж: dotted-numeric и release>prerelease не сломаны
    assert ver.compare_semver("1.0.0-rc2", "1.0.0-rc2") == 0
    assert ver.compare_semver("1.0.0", "1.0.0-rc10") == 1


# ── 13. _check_burned использует численный semver: rc10 НЕ ≤ burned rc2 ──────
def test_check_burned_ranks_rc_numerically() -> None:
    status = {"burned_versions": ["1.0.0-rc2"]}
    pr._check_burned(status, "1.0.0-rc10")  # rc10 > rc2 → НЕ refuse (без исключения)
    for burned_or_below in ("1.0.0-rc2", "1.0.0-rc1"):
        with pytest.raises(SystemExit) as exc:
            pr._check_burned(status, burned_or_below)
        assert "BURNED_VERSION" in str(exc.value)


# ── 14. release-manifest (strict) отказывает при skew/dirty; diagnose — нет ──
def _synced_git_repo(ver, tmp_path: Path) -> None:
    fx.write_all_desktop(tmp_path, fx.VERSION)
    fx.write_version_file(tmp_path, (fx.VERSION + "\n").encode("utf-8"))
    fx.init_git(tmp_path)
    fx.commit_all(tmp_path, "init")


def test_build_manifest_strict_refuses_on_skew(ver, tmp_path: Path) -> None:
    _synced_git_repo(ver, tmp_path)
    fx.write_cargo_toml(tmp_path, "1.0.0-rc4")   # skew (валидная, но иная)
    fx.commit_all(tmp_path, "skew")              # закоммичено → не dirty, только skew
    with pytest.raises(SystemExit) as exc:
        ver.build_manifest(tmp_path, strict=True)
    assert "VERSION_SKEW" in str(exc.value)


def test_build_manifest_strict_refuses_on_dirty(ver, tmp_path: Path) -> None:
    _synced_git_repo(ver, tmp_path)
    # значение версии НЕ меняем (skew нет), но дерево грязное
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "kali"\nversion = "{fx.VERSION}"\n# touched\n',
        encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ver.build_manifest(tmp_path, strict=True)
    assert "RELEASE_MANIFEST_DIRTY" in str(exc.value)


def test_build_manifest_nonstrict_still_reports_dirty(ver, tmp_path: Path) -> None:
    # диагностический (нестрогий) build_manifest НЕ отказывает — показывает dirty=True
    _synced_git_repo(ver, tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "kali"\nversion = "{fx.VERSION}"\n# touched\n',
        encoding="utf-8")
    m = ver.build_manifest(tmp_path)   # strict=False по умолчанию
    assert m["dirty"] is True
