"""F2: сборка desktop не имеет права пачкать tracked-файлы.

Live-gate 2026-07-29 (Gate B): на чистом dedicated worktree сборка оставила

    M src-tauri/Cargo.toml
    M src-tauri/gen/schemas/desktop-schema.json
    M src-tauri/gen/schemas/windows-schema.json
    M ui/tsconfig.tsbuildinfo

``receipts.capture_head_state`` выводит ``dirty`` РОВНО из ``git status
--porcelain``, поэтому receipt получил бы ``dirty: true``, а
``receipts.verify_receipt`` отверг бы его как ``DIRTY_SOURCE`` — то есть
desktop-артефакт не мог заработать clean receipt НИ НА ОДНОМ worktree.

Две причины и два контракта:

* ``ui/tsconfig.tsbuildinfo`` — производный артефакт ``tsc -b``; он не должен
  отслеживаться вовсе;
* ``Cargo.toml`` и сгенерированные схемы tauri перезаписываются с LF, а при
  ``core.autocrlf=true`` checkout кладёт их с CRLF — расхождение только в
  окончаниях строк. Лечится точечными правилами ``text eol=lf``.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GITATTRIBUTES = ROOT / ".gitattributes"
TSBUILDINFO = "ui/tsconfig.tsbuildinfo"

# Файлы, которые перезаписывает сборка tauri, и правило eol=lf обязано их накрыть.
LF_RULED = ("src-tauri/Cargo.toml", "src-tauri/gen/schemas/desktop-schema.json")
# Контроль: путь без правила. Если он НЕ грязнится, фикстура не способна
# обнаружить регрессию и зелёный результат ничего не доказывает.
CONTROL = "src-tauri/control_no_rule.toml"
# Одно и то же СОДЕРЖИМОЕ до и после «сборки»: тогда единственная возможная
# причина грязи — окончания строк, а не изменение текста.
CONTENT_LF = b"[package]\nname = 'x'\nversion = '1'\n"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr}")
    return proc


def _porcelain(repo: Path) -> list[str]:
    out = _git(repo, "status", "--porcelain").stdout.splitlines()
    return [line for line in out if line.strip()]


# ── F2.1/F2.2: производный tsbuildinfo не отслеживается и игнорируется ──────
def test_tsbuildinfo_is_not_tracked() -> None:
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", TSBUILDINFO],
                             capture_output=True, text=True).stdout.strip()
    assert tracked == "", (
        f"{TSBUILDINFO} снова отслеживается — `tsc -b` будет пачкать дерево "
        "и desktop-receipt никогда не станет clean")


def test_tsbuildinfo_is_gitignored() -> None:
    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", TSBUILDINFO],
                             capture_output=True, text=True)
    assert ignored.returncode == 0, f"{TSBUILDINFO} не покрыт .gitignore"


# ── F2.3: правило eol=lf держит status чистым при core.autocrlf=true ────────
def _repo_with_real_gitattributes(tmp_path: Path) -> Path:
    """Репозиторий с core.autocrlf=true и НАСТОЯЩИМ .gitattributes проекта."""
    repo = tmp_path / "repo"
    (repo / "src-tauri" / "gen" / "schemas").mkdir(parents=True)
    for args in (("init",), ("config", "user.email", "t@t"), ("config", "user.name", "T"),
                 ("config", "commit.gpgsign", "false"),
                 ("config", "core.autocrlf", "true")):
        _git(repo, *args)
    shutil.copyfile(GITATTRIBUTES, repo / ".gitattributes")
    for rel in (*LF_RULED, CONTROL):
        (repo / rel).write_bytes(CONTENT_LF)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed")
    # Свежий checkout: только он применяет autocrlf/attributes к байтам на диске.
    for rel in (*LF_RULED, CONTROL):
        (repo / rel).unlink()
    _git(repo, "checkout", "--", ".")
    return repo


def test_lf_rule_keeps_build_rewritten_files_clean(tmp_path: Path) -> None:
    repo = _repo_with_real_gitattributes(tmp_path)
    # Сборка tauri перезаписывает эти файлы ТЕМ ЖЕ текстом, но всегда с LF.
    for rel in (*LF_RULED, CONTROL):
        (repo / rel).write_bytes(CONTENT_LF)
    dirty = {line[3:].strip().strip('"') for line in _porcelain(repo)}
    assert CONTROL in dirty, (
        "контрольный файл без правила не стал грязным — фикстура не воспроизводит "
        "условие autocrlf и зелёный результат ничего не доказывает")
    for rel in LF_RULED:
        assert rel not in dirty, (
            f"{rel} стал грязным после перезаписи с LF — правило `text eol=lf` "
            "отсутствует или не покрывает путь")
