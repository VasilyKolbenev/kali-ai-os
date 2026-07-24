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

import scripts.release.version as relver
from scripts.release import signing_gate

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
    # _fail = bare SystemExit(1), сообщение только в лог (не машинно-читаемо).
    # Для guard-проверок используй _refuse — он несёт reason-token в SystemExit,
    # что делает отказ mutation-provable в тестах.
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

    Примечание: покрытие этой функции полностью subsumed guard-делегацией в
    ``relver.check`` (все 6 desktop-источников + VERSION); оставлена как
    file-name-присутствие + возврат версии для остального pipeline.

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


def _refuse(token: str, detail: str) -> NoReturn:
    """Отказать в публикации с reason-token в сообщении ``SystemExit``.

    Args:
        token: Машинный reason-token (напр. ``FROZEN_HASH``).
        detail: Человекочитаемое уточнение причины.

    Raises:
        SystemExit: Всегда, сообщение начинается с ``token``.
    """
    log.error("%s: %s", token, detail)
    raise SystemExit(f"{token}: {detail}")


def _load_status(repo: Path) -> dict:
    path = repo / "release-status.json"
    if not path.exists():
        _refuse("STATUS_MISSING", f"нет {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
        _refuse("STATUS_MALFORMED", f"release-status.json не читается: {exc}")
    if not isinstance(data, dict):
        _refuse("STATUS_MALFORMED", "release-status.json не является объектом")
    return data


_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_THUMB_RE = re.compile(r"^[0-9a-fA-F]{40}$")  # SHA-1 cert thumbprint


def _validate_status_schema(status: dict) -> None:
    """Строгая fail-closed схема release-status (до чтения VERSION/assets).

    Требования: ``distributable`` — bool; ``canonical_version`` — валидный
    semver; ``burned_versions`` — non-empty уникальный list валидных semver;
    ``frozen_artifacts`` — non-empty list[dict], где каждая запись имеет
    непустые ``name``/``why`` и ``sha256`` ровно из 64 hex-символов.

    Args:
        status: Разобранный release-status.json.

    Raises:
        SystemExit: 'STATUS_SCHEMA' при любом нарушении (пустые списки,
            missing fields, malformed SHA, дубликаты, не-semver).
    """
    if not isinstance(status.get("distributable"), bool):
        _refuse("STATUS_SCHEMA", "distributable обязан быть bool")

    if status.get("distributable") is True:
        thumb = status.get("expected_signer_thumbprint")
        if not (isinstance(thumb, str) and _THUMB_RE.match(thumb)):
            _refuse("STATUS_SCHEMA",
                    "distributable=true обязан задать expected_signer_thumbprint (40-hex)")

    if not relver.is_valid_semver(status.get("canonical_version")):
        _refuse("STATUS_SCHEMA",
                f"canonical_version не semver: {status.get('canonical_version')!r}")

    burned = status.get("burned_versions")
    if not isinstance(burned, list) or not burned:
        _refuse("STATUS_SCHEMA", "burned_versions должен быть non-empty list")
    if not all(relver.is_valid_semver(b) for b in burned):
        _refuse("STATUS_SCHEMA", "burned_versions содержит не-semver")
    if len(set(burned)) != len(burned):
        _refuse("STATUS_SCHEMA", "burned_versions содержит дубликаты")

    frozen = status.get("frozen_artifacts")
    if not isinstance(frozen, list) or not frozen \
            or not all(isinstance(e, dict) for e in frozen):
        _refuse("STATUS_SCHEMA", "frozen_artifacts должен быть non-empty list[dict]")
    for entry in frozen:
        name, why, sha = entry.get("name"), entry.get("why"), entry.get("sha256")
        if not (isinstance(name, str) and name.strip()):
            _refuse("STATUS_SCHEMA", "frozen-запись: пустой name")
        if not (isinstance(why, str) and why.strip()):
            _refuse("STATUS_SCHEMA", "frozen-запись: пустой why")
        if not (isinstance(sha, str) and _HEX64_RE.match(sha)):
            _refuse("STATUS_SCHEMA", f"frozen-запись: sha256 не 64-hex: {sha!r}")


def _hash_assets(dist: Path, assets: list[AssetFile]) -> dict[str, str]:
    dist_root = dist.resolve()
    hashes: dict[str, str] = {}
    for a in assets:
        resolved = a.path.resolve()
        if not resolved.is_relative_to(dist_root):
            _refuse("FROZEN_HASH", f"asset вне dist: {resolved}")
        hashes[a.name] = _sha256(resolved)
    return hashes


def _check_frozen(status: dict, asset_hashes: dict[str, str]) -> None:
    # Схема гарантирует sha256 = чистые 64 hex; сравниваем casefold обе стороны.
    live = {h.casefold() for h in asset_hashes.values()}
    for entry in status.get("frozen_artifacts", []):
        if str(entry["sha256"]).casefold() in live:
            _refuse("FROZEN_HASH", f"asset совпал с frozen {entry.get('name')!r}")


def _check_burned(status: dict, version: str) -> None:
    burned = status.get("burned_versions") or []
    if version in burned or any(relver.compare_semver(version, b) <= 0 for b in burned):
        _refuse("BURNED_VERSION", f"{version} ∈/≤ burned {burned}")


def _check_dirty(repo: Path, dist: Path, allowed_asset_names: set[str]) -> None:
    # Release обязан собираться из ПОЛНОСТЬЮ чистого worktree: любое tracked/
    # untracked изменение (backend/UI/mobile/build scripts/version-файлы) валит
    # publish. Реальный релиз собирается из clean isolated worktree/stage.
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        _refuse("DIRTY_TREE", f"git status упал (fail-closed): {exc}")
    changes = proc.stdout.strip()
    if changes:
        first = changes.splitlines()[0].strip()
        _refuse("DIRTY_TREE", f"worktree не чист ({first} …) — нужен clean stage")
    # gitignored installer-артефакты невидимы git → прямой stat на посторонние файлы.
    for item in dist.iterdir():
        if item.is_file() and item.name != "release-manifest.json" \
                and item.name not in allowed_asset_names:
            _refuse("DIRTY_TREE", f"посторонний файл в installer: {item.name}")


def _check_stale(repo: Path, assets: list[AssetFile]) -> None:
    # mtime — слабый/подделываемый сигнал (touch переставит его вперёд);
    # единственный ЖЁСТКИЙ staleness-гейт — frozen-hash allowlist (_check_frozen).
    try:
        iso = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        _refuse("STALE_ARTIFACT", f"git log упал (fail-closed): {exc}")
    committer_epoch = datetime.fromisoformat(iso).timestamp()
    for a in assets:
        if a.path.stat().st_mtime < committer_epoch:
            _refuse("STALE_ARTIFACT", f"{a.name} старше коммита HEAD")


def _check_manifest(repo: Path, dist: Path, version: str,
                    asset_hashes: dict[str, str]) -> None:
    path = dist / "release-manifest.json"
    if not path.exists():
        _refuse("MANIFEST_MISSING", f"нет {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError, OSError) as exc:
        _refuse("MANIFEST_MISMATCH", f"release-manifest.json не читается: {exc}")
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        _refuse("MANIFEST_MISMATCH", f"git rev-parse упал (fail-closed): {exc}")
    if manifest.get("version") != version:
        _refuse("MANIFEST_MISMATCH", f"version {manifest.get('version')!r} != {version!r}")
    if manifest.get("git_sha") != head:
        _refuse("MANIFEST_MISMATCH", f"git_sha {manifest.get('git_sha')!r} != HEAD")
    if manifest.get("dirty") is not False:
        _refuse("MANIFEST_MISMATCH", "manifest.dirty != false")
    stored = {a.get("name"): a.get("sha256") for a in manifest.get("assets", [])}
    for name, digest in asset_hashes.items():
        if stored.get(name) != digest:
            _refuse("MANIFEST_MISMATCH", f"asset sha256 расходится: {name}")


def verify_release_signature(setup: Path, *, expected_thumbprint: str) -> None:
    """Structured Authenticode gate on the final Setup: exact signer thumbprint +
    valid chain + RFC3161 timestamp (PowerShell inspector). Fail-closed."""
    try:
        signing_gate.verify_signed(setup, expected_thumbprint=expected_thumbprint,
                                   inspector=signing_gate.powershell_inspector)
    except signing_gate.SigningGateError as exc:
        _refuse("SIGN_VERIFY_FAILED", str(exc))


def _check_internal_marker(dist: Path) -> None:
    """Отказать в distributable-публикации внутреннего (unsigned) артефакта."""
    if (dist / signing_gate.INTERNAL_MARKER).exists():
        _refuse("INTERNAL_ARTIFACT", f"{signing_gate.INTERNAL_MARKER} в installer-каталоге")
    for item in dist.glob("*"):
        if signing_gate.INTERNAL_SUFFIX in item.name:
            _refuse("INTERNAL_ARTIFACT", f"internal-маркированный артефакт: {item.name}")


def _check_signature(status: dict, dist: Path, version: str) -> None:
    """Verify the final Setup.exe signature. The schema guarantees a thumbprint at
    distributable=true, so a missing signer never silently skips this gate. The .bin
    slices are protected by the signed Setup and are NOT checked separately."""
    verify_release_signature(dist / f"KALI-Premium-Setup-{version}.exe",
                             expected_thumbprint=status["expected_signer_thumbprint"])


def enforce_release_guard(repo: Path, dist: Path) -> None:
    """Fail-closed release-guard: read-only проверки ДО любого gh/git-push.

    Отказывает при: отсутствии/битом release-status, ``distributable != true``,
    совпадении frozen-hash, сожжённой версии, version-skew, грязном дереве,
    устаревшем артефакте или неверном/отсутствующем манифесте. Каждый отказ —
    ``SystemExit`` с distinct reason-token.

    Args:
        repo: Корень репозитория (release-status.json, version-источники).
        dist: Директория installer-ассетов + release-manifest.json.

    Raises:
        SystemExit: При провале любой проверки (см. reason-tokens).
    """
    # 1) Freeze-first: дёшево и ДО чтения VERSION / collect_assets / hashing
    #    гигабайтных .bin. Компрометированный/frozen workspace не должен даже
    #    стартовать тяжёлые операции.
    status = _load_status(repo)
    _validate_status_schema(status)  # distributable=bool, canonical/burned/frozen валидны
    if status["distributable"] is not True:  # схема гарантирует bool
        _refuse("NOT_DISTRIBUTABLE", "distributable=false (публикация заморожена)")

    # 2) distributable=true: только теперь читаем VERSION, ассеты и хеши.
    version = relver.read_version_file(repo)
    if status.get("canonical_version") != version:
        _refuse("CANONICAL_MISMATCH",
                f"canonical_version {status.get('canonical_version')!r} != VERSION {version!r}")
    # 2a) C8: no internal (unsigned) artifact publishes; the final Setup signature
    #     is verified when an expected signer is configured. Both run AFTER the
    #     freeze gate above (a frozen release never reaches the signature runner).
    _check_internal_marker(dist)
    _check_signature(status, dist, version)
    assets = collect_assets(dist, version)
    asset_hashes = _hash_assets(dist, assets)

    _check_frozen(status, asset_hashes)
    _check_burned(status, version)
    relver.check(repo)  # VERSION_SKEW делегируется version.py
    _check_dirty(repo, dist, {a.name for a in assets})
    _check_stale(repo, assets)
    _check_manifest(repo, dist, version, asset_hashes)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", required=True, help="Release notes (RU, кратко)")
    args = parser.parse_args()
    enforce_release_guard(REPO_ROOT, DIST_DIR)  # fail-closed, ДО gh/git-push
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
