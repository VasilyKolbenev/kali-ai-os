"""Публикация релиза KALI: валидация версий → draft GH-релиз → ассеты → undraft →
коммит releases/latest.json (атомарный флип — клиенты видят версию последним шагом).

Использование (после build → frozen_smoke):
    .venv\\Scripts\\python.exe scripts\\publish_release.py --notes "Что нового"

Спека: docs/superpowers/specs/2026-07-14-auto-update-design.md §Публикация.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

log = logging.getLogger("publish_release")

REPO_SLUG = "VasilyKolbenev/kali-ai-os"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist_premium" / "installer"
MANIFEST_PATH = REPO_ROOT / "releases" / "latest.json"


@dataclass
class AssetFile:
    name: str
    path: Path


def _fail(msg: str) -> NoReturn:
    log.error(msg)
    raise SystemExit(1)


def _read_tauri_version(repo: Path) -> str:
    conf = json.loads((repo / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    return str(conf["version"])


def _read_cargo_version(repo: Path) -> str:
    text = (repo / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        _fail("Cargo.toml: version не найдена")
    return m.group(1)


def _read_iss_version(repo: Path) -> str:
    text = (repo / "scripts" / "installer_premium.iss").read_text(encoding="utf-8")
    m = re.search(r'#define AppVersion "([^"]+)"', text)
    if not m:
        _fail("installer_premium.iss: AppVersion не найден")
    return m.group(1)


def validate_versions(repo: Path, dist: Path) -> str:
    """Единство версии: tauri.conf == Cargo.toml == .iss == имена файлов.

    Расхождение = update-петля (апп обновился, считает себя старым) — hard fail.

    Args:
        repo: Корень репозитория с src-tauri/ и scripts/.
        dist: Директория installer-ассетов (Setup.exe + .bin слайсы).

    Returns:
        Единая версия релиза.

    Raises:
        SystemExit: При любом расхождении версий.
    """
    tauri = _read_tauri_version(repo)
    cargo = _read_cargo_version(repo)
    iss = _read_iss_version(repo)
    if not (tauri == cargo == iss):
        _fail(f"Версии расходятся: tauri.conf={tauri} Cargo.toml={cargo} iss={iss}")
    if not (dist / f"KALI-Premium-Setup-{tauri}.exe").exists():
        _fail(f"В {dist} нет KALI-Premium-Setup-{tauri}.exe — версия файлов иная?")
    return tauri


def collect_assets(dist: Path, version: str) -> list[AssetFile]:
    """Setup.exe + все .bin-слайсы; exe строго первым (контракт манифеста —
    Rust берёт assets[0] как исполняемый setup).

    Args:
        dist: Директория installer-ассетов.
        version: Версия релиза.

    Returns:
        Список ассетов: exe первым, затем непрерывные .bin слайсы.

    Raises:
        SystemExit: Если exe или хотя бы один слайс отсутствует / слайсы не непрерывны.
    """
    exe = dist / f"KALI-Premium-Setup-{version}.exe"
    if not exe.exists():
        _fail(f"Нет {exe}")
    # Лексикографическая сортировка верна при <10 слайсах (наш случай: 5.8GB/2GB=3);
    # при ≥10 понадобилась бы числовая сортировка суффикса.
    bins = sorted(dist.glob(f"KALI-Premium-Setup-{version}-*.bin"))
    if not bins:
        _fail("Не найдено ни одного .bin-слайса (DiskSpanning)")
    expected = {f"KALI-Premium-Setup-{version}-{i}.bin" for i in range(1, len(bins) + 1)}
    actual = {b.name for b in bins}
    if expected != actual:
        _fail(f"Слайсы не непрерывны: {sorted(actual)}")
    return [AssetFile(exe.name, exe)] + [AssetFile(b.name, b) for b in bins]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    version: str, notes: str, assets: list[AssetFile], pub_date: str | None = None
) -> dict:
    """Собрать манифест обновления (name/url/sha256/size на каждый ассет).

    Args:
        version: Версия релиза.
        notes: Release notes.
        assets: Ассеты из collect_assets (exe первым).
        pub_date: ISO-дата публикации; по умолчанию — текущий UTC.

    Returns:
        Словарь манифеста, готовый к сериализации в releases/latest.json.
    """
    return {
        "version": version,
        "pub_date": pub_date or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes,
        "assets": [
            {
                "name": a.name,
                "url": f"https://github.com/{REPO_SLUG}/releases/download/v{version}/{a.name}",
                "sha256": _sha256(a.path),
                "size": a.path.stat().st_size,
            }
            for a in assets
        ],
    }


def _run(cmd: list[str]) -> None:
    log.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def publish(version: str, notes: str, assets: list[AssetFile]) -> None:
    """Создать draft GH-релиз, залить ассеты, снять draft (undraft последним).

    Args:
        version: Версия релиза.
        notes: Release notes.
        assets: Ассеты для загрузки.

    Raises:
        SystemExit: Если релиз на теге существует в неверном состоянии
            (не draft и не совпадает с текущей версией), либо gh вернул
            неразбираемый ответ.
    """
    tag = f"v{version}"
    prerelease = ["--prerelease"] if "-" in version else []
    # Идемпотентность: битый draft с прошлого падения — пересоздать; уже
    # опубликованный этот же релиз (publish отработал, флип упал) — пропустить.
    view = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft,tagName"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if view.returncode == 0:
        # returncode==0 с пустым/битым stdout — неожиданное состояние, не глотаем.
        try:
            info = json.loads(view.stdout)
        except json.JSONDecodeError:
            _fail(f"gh release view {tag}: неразбираемый ответ: {view.stdout!r}")
        if info.get("isDraft"):
            log.info("Найден draft %s с прошлого запуска — удаляю и пересоздаю", tag)
            # --cleanup-tag: не оставлять осиротевший тег, пиннящий старый коммит.
            _run(["gh", "release", "delete", tag, "--yes", "--cleanup-tag"])
        elif info.get("tagName") == tag:
            # Не-draft релиз на теге v{version} ЕСТЬ эта версия — publish уже
            # отработал (флип упал в прошлый раз). Идемпотентно к флипу манифеста.
            log.info("Релиз %s уже опубликован — перехожу к флипу манифеста", tag)
            return
        else:
            _fail(f"Релиз {tag} уже опубликован в неверном состоянии "
                  f"(tagName={info.get('tagName')!r})")
    _run(["gh", "release", "create", tag, "--draft", "--title", f"KALI {version}",
          "--notes", notes, *prerelease])
    for a in assets:
        _run(["gh", "release", "upload", tag, str(a.path)])
    _run(["gh", "release", "edit", tag, "--draft=false"])


def flip_manifest(manifest: dict) -> None:
    """Записать и закоммитить releases/latest.json — атомарный флип публикации.

    Args:
        manifest: Манифест из build_manifest.
    """
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _run(["git", "add", str(MANIFEST_PATH)])
    # pathspec: не подметать чужой staged-мусор в релизный коммит
    _run(["git", "commit", "-m", f"release: latest.json -> {manifest['version']}",
          "--", str(MANIFEST_PATH)])
    _run(["git", "push", "origin", "main"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", required=True, help="Release notes (RU, кратко)")
    args = parser.parse_args()
    version = validate_versions(REPO_ROOT, DIST_DIR)
    assets = collect_assets(DIST_DIR, version)
    manifest = build_manifest(version, args.notes, assets)
    publish(version, args.notes, assets)
    try:
        flip_manifest(manifest)  # ПОСЛЕДНИМ — атомарный флип
    except Exception:
        # Релиз уже публичен; манифест — единственный незавершённый шаг.
        # Повторный запуск идемпотентен (publish пропустит уже-опубликованный).
        log.error(
            "Релиз опубликован, но манифест НЕ флипнут. "
            "Выполни вручную: git push origin main"
        )
        raise
    log.info("Опубликовано: %s (%d ассетов)", version, len(assets))


if __name__ == "__main__":
    main()
