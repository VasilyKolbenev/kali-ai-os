"""TDD (red-first) для publish-guard в scripts/publish_release.py.

`enforce_release_guard(repo, dist)` ещё не написан → все refuse-тесты падают
сегодня (AttributeError/иное). Guard read-only (stat/hash/git status/rev-parse/
git log), вызывается ПЕРВЫМ в main() до любого gh/git-push. Каждый refuse-тест
делит `_green_baseline()` и возмущает ровно одну ось; assert конкретного
reason-token (mutation-provability).

Настоящий git-репо в tmp_path через subprocess допустим (guard читает git).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.publish_release as pr

import _guard_fixtures as fx

# Оригинальный subprocess.run — для делегации read-only git внутри fake.
REAL_RUN = subprocess.run
DEFAULT_EXE = b"fresh-exe"


# ── green baseline: всё зелёное, каждый тест ломает одну ось ─────────────────
@pytest.fixture(autouse=True)
def _stub_signature_verifier(monkeypatch):
    """The structured Authenticode verify needs a real signed Setup — default it to a
    no-op so the non-signature axes test in isolation. Signature-specific tests
    re-monkeypatch pr.verify_release_signature with their own spy/failing stub."""
    monkeypatch.setattr(pr, "verify_release_signature", lambda *a, **k: None)


def _green_baseline(tmp_path: Path, *, version: str = fx.VERSION,
                    mobile: str = "0.1.0+1", distributable=True,
                    frozen=None, burned=None, committer_date: str | None = None,
                    exe_bytes: bytes = DEFAULT_EXE,
                    expected_signer_thumbprint: str | None = fx.SIGNER_THUMBPRINT) -> SimpleNamespace:
    """Полностью проходящий репо+dist: synced-версии, clean git, свежий артефакт,
    distributable=true+signer thumbprint, валидный release-manifest, non-empty frozen."""
    repo = tmp_path
    fx.write_all_desktop(repo, version, mobile)
    fx.write_version_file(repo, (version + "\n").encode("utf-8"))
    fx.write_status(repo, distributable=distributable, frozen=frozen, burned=burned,
                    canonical=version, expected_signer_thumbprint=expected_signer_thumbprint)
    (repo / ".gitignore").write_text("dist_premium/\n", encoding="utf-8")
    fx.init_git(repo)
    fx.commit_all(repo, "baseline", date=committer_date)
    sha = fx.head_sha(repo)
    dist = fx.mk_dist(repo, version, exe_bytes=exe_bytes)
    assets = fx.dist_assets(dist, version)
    fx.write_manifest(dist, version, sha, False, assets, mobile_version=mobile)
    fx.set_asset_mtime(dist, version, fx.committer_epoch(repo) + 3600.0)  # свежий
    return SimpleNamespace(repo=repo, dist=dist, version=version, sha=sha,
                           assets=assets, exe=assets[0])


def _guard(b: SimpleNamespace) -> None:
    pr.enforce_release_guard(b.repo, b.dist)


# ── main()-драйверы (fake subprocess: gh/git не запускаются реально) ─────────
def _drive_main(monkeypatch, repo: Path, dist: Path, fake_run) -> None:
    monkeypatch.setattr(pr, "REPO_ROOT", repo)
    monkeypatch.setattr(pr, "DIST_DIR", dist)
    monkeypatch.setattr(pr, "MANIFEST_PATH", repo / "releases" / "latest.json")
    monkeypatch.setattr(pr.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["publish_release.py", "--notes", "t"])
    pr.main()


def _forbidding_fake(calls: list):
    """Записывает cmd; поднимает при любом gh или git-мутирующем; read-only git → real."""
    def run(cmd, *a, **k):  # noqa: ANN001
        calls.append(list(cmd))
        if cmd and cmd[0] == "gh":
            raise AssertionError(f"gh invoked before guard passed: {cmd}")
        if cmd and cmd[0] == "git":
            if cmd[1] in {"add", "commit", "push", "tag"}:
                raise AssertionError(f"git mutating before guard passed: {cmd}")
            return REAL_RUN(cmd, *a, **k)
        return subprocess.CompletedProcess(cmd, 0, stdout="")
    return run


def _allowing_fake(calls: list):
    """gh release view → rc1 (нет релиза); прочее gh/git-mutating → записать rc0;
    read-only git → real."""
    def run(cmd, *a, **k):  # noqa: ANN001
        calls.append(list(cmd))
        if cmd and cmd[0] == "gh":
            if list(cmd[1:3]) == ["release", "view"]:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="nf")
            return subprocess.CompletedProcess(cmd, 0, stdout="")
        if cmd and cmd[0] == "git":
            if cmd[1] in {"add", "commit", "push", "tag"}:
                return subprocess.CompletedProcess(cmd, 0, stdout="")
            return REAL_RUN(cmd, *a, **k)
        return subprocess.CompletedProcess(cmd, 0, stdout="")
    return run


def _has_mutating(calls: list) -> bool:
    for c in calls:
        if c and c[0] == "gh":
            return True
        if c and c[0] == "git" and len(c) > 1 and c[1] in {"add", "commit", "push", "tag"}:
            return True
    return False


# ── 1. FROZEN_HASH: нормализация формы хранимого хеша ───────────────────────
@pytest.mark.parametrize("form", ["upper", "lower", "mixed"])
def test_publish_refuses_on_frozen_hash(tmp_path: Path, form: str) -> None:
    # Схема требует ровно 64 hex → нормализация только case (0x/spaces теперь
    # ловятся схемой как STATUS_SCHEMA, см. test_status_schema_rejects_bad_sha).
    real = fx.sha256_bytes(DEFAULT_EXE)          # реальный lowercase hexdigest exe
    stored = {
        "upper": real.upper(),
        "lower": real,
        "mixed": real[:32].upper() + real[32:],
    }[form]
    b = _green_baseline(tmp_path, frozen=[{"name": "x", "sha256": stored, "why": "d"}])
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "FROZEN_HASH" in str(exc.value)


# ── 2. NOT_DISTRIBUTABLE: строго bool True ──────────────────────────────────
def test_publish_refuses_when_distributable_false(tmp_path: Path) -> None:
    # bool False → NOT_DISTRIBUTABLE (валидная схема, публикация заморожена)
    b = _green_baseline(tmp_path, distributable=False)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "NOT_DISTRIBUTABLE" in str(exc.value)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, fx._ABSENT])
def test_publish_rejects_non_bool_distributable(tmp_path: Path, value) -> None:
    # не-bool / missing → STATUS_SCHEMA (distributable обязан быть bool)
    b = _green_baseline(tmp_path, distributable=value)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)


def test_distributable_json_true_passes_axis(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, distributable=True)
    _guard(b)  # зелёный — не должен поднять исключение


# ── 3. STATUS_MISSING / битый JSON: без сетевых/gh/git-mutating вызовов ──────
def test_publish_refuses_when_release_status_missing(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    (b.repo / "release-status.json").unlink()
    calls: list = []
    with pytest.raises(SystemExit) as exc:
        _drive_main(monkeypatch, b.repo, b.dist, _forbidding_fake(calls))
    assert "STATUS_MISSING" in str(exc.value)
    assert not _has_mutating(calls)


def test_publish_refuses_when_release_status_malformed(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    fx.write_status(b.repo, raw="{ garbage")
    calls: list = []
    with pytest.raises(SystemExit):
        _drive_main(monkeypatch, b.repo, b.dist, _forbidding_fake(calls))
    assert not _has_mutating(calls)


# ── 4. release-status читается из repo-root, не из cwd ───────────────────────
def test_status_path_is_repo_anchored(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, distributable=False)
    forge = tmp_path.parent / "forge_cwd"
    forge.mkdir(exist_ok=True)
    fx.write_status(forge, distributable=True)   # подделка в cwd
    monkeypatch.chdir(forge)
    with pytest.raises(SystemExit) as exc:
        _guard(b)                                # читает repo/release-status.json (false)
    assert "NOT_DISTRIBUTABLE" in str(exc.value)


# ── 5. guard выполняется до любого gh/git-mutating вызова ────────────────────
def test_guard_runs_before_any_gh_or_git_call(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, distributable=False)   # заведомо не проходит guard
    calls: list = []
    with pytest.raises(SystemExit):
        _drive_main(monkeypatch, b.repo, b.dist, _forbidding_fake(calls))
    assert not _has_mutating(calls)


# ── 6. frozen блокирует даже при distributable=true (ALL-OF) ────────────────
def test_frozen_hash_refuses_even_when_distributable_true(tmp_path: Path) -> None:
    frozen_sha = fx.sha256_bytes(DEFAULT_EXE)
    b = _green_baseline(tmp_path, distributable=True,
                        frozen=[{"name": "x", "sha256": frozen_sha, "why": "d"}])
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "FROZEN_HASH" in str(exc.value)


# ── 7. frozen матчит ЛЮБОЙ asset по контенту (exe и .bin) ────────────────────
@pytest.mark.parametrize("target", ["exe", "bin"])
def test_frozen_hash_matches_any_asset_by_content(tmp_path: Path, target: str) -> None:
    frozen_sha = fx.sha256_bytes(DEFAULT_EXE if target == "exe" else b"bin2")
    b = _green_baseline(tmp_path,
                        frozen=[{"name": "n", "sha256": frozen_sha, "why": "d"}])
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "FROZEN_HASH" in str(exc.value)


# ── 8. frozen_artifacts обязан быть non-empty при distributable=false ────────
@pytest.mark.parametrize("kind", ["empty", "missing"])
def test_frozen_artifacts_must_be_nonempty_when_blocking(tmp_path: Path, kind: str) -> None:
    if kind == "empty":
        b = _green_baseline(tmp_path, distributable=False, frozen=[])
    else:
        repo = tmp_path
        fx.write_all_desktop(repo, fx.VERSION)
        fx.write_version_file(repo, b"1.0.0-rc3\n")
        fx.write_status(repo, distributable=False, drop_frozen=True)
        (repo / ".gitignore").write_text("dist_premium/\n", encoding="utf-8")
        fx.init_git(repo)
        fx.commit_all(repo, "baseline")
        dist = fx.mk_dist(repo, fx.VERSION)
        assets = fx.dist_assets(dist, fx.VERSION)
        fx.write_manifest(dist, fx.VERSION, fx.head_sha(repo), False, assets)
        fx.set_asset_mtime(dist, fx.VERSION, fx.committer_epoch(repo) + 3600.0)
        b = SimpleNamespace(repo=repo, dist=dist)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)   # схема требует non-empty frozen


# ── 9. DIRTY_TREE: version-источник / release-status изменены после коммита ──
def test_publish_refuses_when_version_source_dirty(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    # Cargo.toml изменён (значение всё ещё rc3) → unstaged diff vs HEAD
    (b.repo / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nname = "kali-desktop"\nversion = "1.0.0-rc3"\n# touched\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


def test_publish_refuses_when_release_status_uncommitted(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    status = b.repo / "release-status.json"
    status.write_text(status.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


# ── 10. DIRTY_TREE: посторонний файл в gitignored installer (прямой stat) ────
def test_publish_refuses_when_installer_dir_dirty(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    (b.dist / "leftover-unstaged.tmp").write_bytes(b"stray")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


# ── 11. dirty-scoping + fail-closed ─────────────────────────────────────────
def _dirty_source(b):
    (b.repo / "src-tauri" / "Cargo.toml").write_text(
        '[package]\nname = "kali-desktop"\nversion = "1.0.0-rc3"\n# x\n', encoding="utf-8")


def _dirty_version(b):
    (b.repo / "VERSION").write_bytes(b"1.0.0-rc3\n\n")


def _dirty_status(b):
    p = b.repo / "release-status.json"
    p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")


def _dirty_releases(b):
    (b.repo / "releases").mkdir(exist_ok=True)
    (b.repo / "releases" / "latest.json").write_text("{}", encoding="utf-8")


def _dirty_installer(b):
    (b.dist / "stray.tmp").write_bytes(b"x")


@pytest.mark.parametrize("perturb", [
    _dirty_source, _dirty_version, _dirty_status, _dirty_releases, _dirty_installer,
])
def test_dirty_check_scoping_refuses_each_release_path(tmp_path: Path, perturb) -> None:
    b = _green_baseline(tmp_path)
    perturb(b)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


def test_dirty_check_refuses_on_any_tracked_change(tmp_path: Path) -> None:
    # Codex review: release обязан собираться из ПОЛНОСТЬЮ чистого worktree.
    # Любое untracked/tracked изменение (даже docs/) => DIRTY_TREE.
    b = _green_baseline(tmp_path)
    (b.repo / "docs").mkdir(exist_ok=True)
    (b.repo / "docs" / "notes.md").write_text("scratch", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


@pytest.mark.parametrize("relpath", [
    "kernel/main.py", "ui/src/App.tsx", "scripts/build_installer_premium.bat",
])
def test_dirty_check_refuses_backend_ui_build_change(tmp_path: Path, relpath: str) -> None:
    # backend/UI/build-script правки обязаны валить release-guard (не только version-файлы).
    b = _green_baseline(tmp_path)
    p = b.repo / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("orig\n", encoding="utf-8")
    fx.commit_all(b.repo, "add source")          # tracked + clean
    p.write_text("modified\n", encoding="utf-8")  # dirty vs HEAD
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "DIRTY_TREE" in str(exc.value)


def test_dirty_check_fail_closed_on_git_error(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)

    def boom(cmd, *a, **k):  # noqa: ANN001
        if cmd and cmd[0] == "git" and len(cmd) > 1 and cmd[1] == "status":
            raise subprocess.CalledProcessError(1, cmd)
        return REAL_RUN(cmd, *a, **k)

    monkeypatch.setattr(pr.subprocess, "run", boom)
    with pytest.raises(SystemExit):
        _guard(b)   # git status упал → fail-closed


# ── 12. STALE_ARTIFACT: committer-эпоха при non-UTC оффсете ──────────────────
def test_publish_refuses_on_stale_artifact_by_committer_epoch(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, committer_date="2026-07-17T12:00:00+05:30")
    epoch = fx.committer_epoch(b.repo)
    fx.set_asset_mtime(b.dist, b.version, epoch - 1.0)   # артефакт старше коммита
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STALE_ARTIFACT" in str(exc.value)


def test_fresh_artifact_passes_staleness_axis(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, committer_date="2026-07-17T12:00:00+05:30")
    epoch = fx.committer_epoch(b.repo)
    fx.set_asset_mtime(b.dist, b.version, epoch + 1.0)   # на 1с позже → свежий
    _guard(b)  # ось staleness пройдена (репо иначе зелёный)


# ── 13. frozen блокирует даже «свежий» (touched) артефакт ───────────────────
def test_frozen_hash_still_blocks_touched_artifact(tmp_path: Path) -> None:
    frozen_sha = fx.sha256_bytes(DEFAULT_EXE)
    b = _green_baseline(tmp_path,
                        frozen=[{"name": "x", "sha256": frozen_sha, "why": "d"}])
    import time
    fx.set_asset_mtime(b.dist, b.version, time.time() + 5.0)  # свежий → staleness ok
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "FROZEN_HASH" in str(exc.value)


# ── 14. MANIFEST_MISSING / MANIFEST_MISMATCH ────────────────────────────────
def test_publish_refuses_on_manifest_missing(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    (b.dist / "release-manifest.json").unlink()
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "MANIFEST_MISSING" in str(exc.value)


@pytest.mark.parametrize("mode", ["version", "git_sha", "dirty", "asset_sha"])
def test_publish_refuses_on_manifest_mismatch(tmp_path: Path, mode: str) -> None:
    b = _green_baseline(tmp_path)
    if mode == "version":
        fx.write_manifest(b.dist, "9.9.9", b.sha, False, b.assets)
    elif mode == "git_sha":
        fx.write_manifest(b.dist, b.version, "0" * 40, False, b.assets)
    elif mode == "dirty":
        fx.write_manifest(b.dist, b.version, b.sha, True, b.assets)
    else:  # asset_sha
        fx.write_manifest(b.dist, b.version, b.sha, False, b.assets,
                          asset_sha_override={b.exe.name: "0" * 64})
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "MANIFEST_MISMATCH" in str(exc.value)


# ── 15. BURNED_VERSION: пересобранный rc2 (новые байты, но версия сожжена) ───
def test_publish_refuses_at_or_below_burned_version(tmp_path: Path) -> None:
    # rc2 ∈ burned_versions; frozen по умолчанию (rc2-sha) НЕ совпадёт со свежими байтами
    b = _green_baseline(tmp_path, version="1.0.0-rc2", exe_bytes=b"rebuilt-rc2")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "BURNED_VERSION" in str(exc.value)


# ── 15b. VERSION_SKEW: один desktop-источник уведён на валидную-но-иную версию ─
def test_publish_refuses_on_version_skew(tmp_path: Path) -> None:
    # Из зелёного baseline уводим ЛИШЬ Cargo.toml на валидный rc4 → skew.
    # VERSION_SKEW (relver.check) обязан сработать РАНЬШЕ dirty/stale.
    b = _green_baseline(tmp_path)
    fx.write_cargo_toml(b.repo, "1.0.0-rc4")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "VERSION_SKEW" in str(exc.value)


# ── 15c. asset — симлинк, резолвящийся ВНЕ dist (escape) ─────────────────────
def test_publish_refuses_on_symlink_escape(tmp_path: Path, caplog) -> None:
    # H6-5: теперь это ловится РАНЬШЕ и строже — подменённые байты расходятся с
    # запечатанным artifact-манифестом (ARTIFACT_HASH_MISMATCH) ещё до FROZEN_HASH.
    b = _green_baseline(tmp_path)
    exe = b.dist / f"KALI-Premium-Setup-{b.version}.exe"
    outside = tmp_path.parent / "outside-exe.bin"
    outside.write_bytes(b"outside-content")
    exe.unlink()
    try:
        os.symlink(outside, exe)
    except (OSError, NotImplementedError):
        pytest.skip("no symlink privilege")
    with caplog.at_level("ERROR"), pytest.raises(SystemExit):
        _guard(b)
    # H7-2 ловит это ещё раньше: символьная ссылка в манифесте — ARTIFACT_REPARSE
    reasons = caplog.text
    assert any(token in reasons for token in
               ("OUTPUT_REPARSE_IN_TREE", "ARTIFACT_REPARSE", "ARTIFACT_HASH_MISMATCH",
                "FROZEN_HASH"))


# ── 16. всё зелёное → guard пропускает, publish отрабатывает ─────────────────
def test_publish_proceeds_when_all_green(monkeypatch, tmp_path: Path) -> None:
    assert hasattr(pr, "enforce_release_guard")  # guard существует (red сегодня)
    b = _green_baseline(tmp_path)
    calls: list = []
    _drive_main(monkeypatch, b.repo, b.dist, _allowing_fake(calls))  # без SystemExit
    ghc = [c for c in calls if c[:2] == ["gh", "release"]]
    assert any(c[2] == "create" for c in ghc)
    assert any(c[2] == "upload" for c in ghc)
    assert any(c[2] == "edit" for c in ghc)


# ── 17. freeze short-circuits ДО collect_assets/hashing гигабайтных файлов ────
def test_freeze_short_circuits_before_reading_assets(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path, distributable=False)
    spy = {"collect": 0, "sha": 0}

    def _collect(*a, **k):  # noqa: ANN002, ANN003
        spy["collect"] += 1
        return []

    def _sha(*a, **k):  # noqa: ANN002, ANN003
        spy["sha"] += 1
        return "x"

    monkeypatch.setattr(pr, "collect_assets", _collect)
    monkeypatch.setattr(pr, "_sha256", _sha)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "NOT_DISTRIBUTABLE" in str(exc.value)
    assert spy == {"collect": 0, "sha": 0}   # ассеты не читались и не хешировались


# ── 18. canonical_version в release-status обязан совпадать с VERSION ─────────
def test_publish_refuses_on_canonical_mismatch(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    fx.write_status(b.repo, distributable=True, canonical="9.9.9")  # != VERSION rc3
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "CANONICAL_MISMATCH" in str(exc.value)


# ── 19. schema release-status: burned/frozen неверного типа → fail-closed ─────
@pytest.mark.parametrize("bad", ["burned", "frozen"])
def test_status_schema_rejects_bad_types(tmp_path: Path, bad: str) -> None:
    b = _green_baseline(tmp_path)
    if bad == "burned":
        fx.write_status(b.repo, distributable=True, burned="not-a-list")
    else:
        fx.write_status(b.repo, distributable=True, frozen="not-a-list")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)


_GOOD_SHA = fx.FROZEN_RC2_SHA  # валидный 64-hex (в нижнем регистре ок для схемы)


@pytest.mark.parametrize("mutate", [
    # canonical_version не semver
    lambda: dict(canonical="not-semver"),
    # burned: пустой / не-semver / дубликаты
    lambda: dict(burned=[]),
    lambda: dict(burned=["not-semver"]),
    lambda: dict(burned=["1.0.0-rc2", "1.0.0-rc2"]),
    # frozen: пустой
    lambda: dict(frozen=[]),
    # frozen-запись без обязательных полей
    lambda: dict(frozen=[{"sha256": _GOOD_SHA, "why": "d"}]),          # нет name
    lambda: dict(frozen=[{"name": "n", "sha256": _GOOD_SHA}]),         # нет why
    lambda: dict(frozen=[{"name": "n", "why": "d"}]),                  # нет sha
    lambda: dict(frozen=[{"name": "", "sha256": _GOOD_SHA, "why": "d"}]),   # пустой name
    lambda: dict(frozen=[{"name": "n", "sha256": _GOOD_SHA, "why": " "}]),  # пустой why
    # sha неверной длины / не-hex
    lambda: dict(frozen=[{"name": "n", "sha256": _GOOD_SHA[:63], "why": "d"}]),   # 63
    lambda: dict(frozen=[{"name": "n", "sha256": _GOOD_SHA + "a", "why": "d"}]),  # 65
    lambda: dict(frozen=[{"name": "n", "sha256": "z" * 64, "why": "d"}]),         # не-hex
], ids=["canonical", "burned_empty", "burned_nonsemver", "burned_dup",
        "frozen_empty", "frozen_no_name", "frozen_no_why", "frozen_no_sha",
        "frozen_empty_name", "frozen_empty_why", "sha_63", "sha_65", "sha_nonhex"])
def test_status_schema_rejects_malformed_fields(tmp_path: Path, mutate) -> None:
    b = _green_baseline(tmp_path)
    fx.write_status(b.repo, distributable=True, **mutate())
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)


def test_unprotected_rebuilt_rc2_is_blocked(tmp_path: Path) -> None:
    # rebuilt rc2: новые байты (hash НЕ во frozen), но версия ∈ burned →
    # current VERSION не строго выше всех burned → BURNED_VERSION.
    b = _green_baseline(tmp_path, version="1.0.0-rc2", exe_bytes=b"rebuilt-rc2-fresh")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "BURNED_VERSION" in str(exc.value)


# ── F4 (OPUS-201): structured signature / internal guard, freeze-first preserved ─
def test_signature_checker_not_called_when_not_distributable(monkeypatch, tmp_path: Path) -> None:
    # freeze-first: NOT_DISTRIBUTABLE refuses BEFORE the signature runner (F4#13).
    b = _green_baseline(tmp_path, distributable=False)
    calls: list = []
    monkeypatch.setattr(pr, "verify_release_signature", lambda *a, **k: calls.append(1))
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "NOT_DISTRIBUTABLE" in str(exc.value)
    assert calls == []  # neither signtool nor the inspector ran on a frozen release


def test_distributable_verifies_setup_signature_exe_only(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    seen: list = []
    monkeypatch.setattr(pr, "verify_release_signature",
                        lambda setup, *, expected_thumbprint: seen.append((setup.name, expected_thumbprint)))
    _guard(b)
    assert len(seen) == 1  # exactly one call — the final Setup EXE
    assert seen[0][1] == fx.SIGNER_THUMBPRINT
    assert seen[0][0].endswith(".exe") and ".bin" not in seen[0][0]  # .bin NOT signature-checked


def test_refuses_when_signature_verification_fails(monkeypatch, tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)

    def _boom(setup, *, expected_thumbprint):  # noqa: ANN001
        pr._refuse("SIGN_VERIFY_FAILED", "thumbprint/timestamp mismatch")

    monkeypatch.setattr(pr, "verify_release_signature", _boom)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "SIGN_VERIFY_FAILED" in str(exc.value)


def test_refuses_internal_marked_artifact(tmp_path: Path) -> None:
    b = _green_baseline(tmp_path)
    (b.dist / "INTERNAL-UNSIGNED.txt").write_text("do not distribute", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "INTERNAL_ARTIFACT" in str(exc.value)


def test_distributable_requires_signer_thumbprint(tmp_path: Path) -> None:
    # F4#10/#11: a distributable=true release with NO expected signer thumbprint is a
    # schema violation — it never silently skips the signature gate.
    b = _green_baseline(tmp_path, expected_signer_thumbprint=None)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)


@pytest.mark.parametrize("bad", ["", "not-hex", "A1B2"])  # empty / non-hex / too short
def test_distributable_rejects_malformed_thumbprint(tmp_path: Path, bad: str) -> None:
    b = _green_baseline(tmp_path, expected_signer_thumbprint=bad)
    with pytest.raises(SystemExit) as exc:
        _guard(b)
    assert "STATUS_SCHEMA" in str(exc.value)
