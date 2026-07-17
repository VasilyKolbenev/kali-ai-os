"""Единый version source-of-truth для KALI (OPUS-002).

Канонический источник — файл ``VERSION`` в корне репозитория (одна строка,
semver с опциональным pre-release). Шесть desktop-источников обязаны совпадать
с ``VERSION``; mobile (``pubspec.yaml``) валидируется как ``X.Y.Z+N``, но не
обязан равняться desktop-версии.

Модуль — чистый file/git IO, без сети. Валидация выполняется на границах:
некорректные данные отклоняются как ``SystemExit`` с reason-token в сообщении
(``VERSION_INVALID`` / ``VERSION_SKEW`` / ``MOBILE_VERSION_INVALID``).

CLI::

    python -m scripts.release.version check
    python -m scripts.release.version sync
    python -m scripts.release.version manifest
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

log = logging.getLogger("release.version")

REPO_ROOT = Path(__file__).resolve().parents[2]

DESKTOP_KEYS = ("pyproject", "kernel", "cargo_toml", "cargo_lock", "tauri", "iss")

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.\-]+)?$")
_MOBILE_RE = re.compile(r"^\d+\.\d+\.\d+\+\d+$")
_ALNUM_SPLIT_RE = re.compile(r"^([A-Za-z]+)(\d+)$")
_KERNEL_RE = re.compile(
    r"""__version__\s*(?::\s*str)?\s*=\s*['"]([^'"]+)['"]"""
)
_ISS_RE = re.compile(r'#define\s+AppVersion\s+"([^"]+)"')


def _fail(msg: str) -> NoReturn:
    """Отказать с reason-token в сообщении ``SystemExit`` (fail-closed).

    Args:
        msg: Человекочитаемое сообщение, содержащее reason-token.

    Raises:
        SystemExit: Всегда, с кодом-сообщением ``msg``.
    """
    log.error(msg)
    raise SystemExit(msg)


# ── VERSION file ────────────────────────────────────────────────────────────
def read_version_file(repo: Path) -> str:
    """Прочитать канонический ``VERSION`` (BOM/CRLF-толерантно).

    Args:
        repo: Корень репозитория.

    Returns:
        Валидная semver-строка без окружающих пробелов.

    Raises:
        SystemExit: Если файл пуст/многострочный/не semver ('VERSION_INVALID').
    """
    raw = (repo / "VERSION").read_text(encoding="utf-8-sig").strip()
    if not raw or "\n" in raw or not _SEMVER_RE.match(raw):
        _fail(f"VERSION_INVALID: {raw!r} — ожидается MAJOR.MINOR.PATCH[-prerelease]")
    return raw


# ── desktop sources (readers) ───────────────────────────────────────────────
def _read_pyproject(repo: Path) -> str:
    data = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if not isinstance(version, str):
        _fail("VERSION_INVALID pyproject: [project].version отсутствует или dynamic")
    return version


def _read_kernel(repo: Path) -> str:
    text = (repo / "kernel" / "__init__.py").read_text(encoding="utf-8")
    m = _KERNEL_RE.search(text)
    if not m:
        _fail("VERSION_INVALID kernel: __version__ не найден в kernel/__init__.py")
    return m.group(1)


def _read_cargo_toml(repo: Path) -> str:
    data = tomllib.loads((repo / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    version = data.get("package", {}).get("version")
    if not isinstance(version, str):
        _fail("VERSION_INVALID cargo_toml: [package].version отсутствует")
    return version


def _read_cargo_lock(repo: Path) -> str:
    text = (repo / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8")
    for block in text.split("[[package]]")[1:]:
        name_m = re.search(r'^name\s*=\s*"([^"]+)"', block, re.MULTILINE)
        if name_m and name_m.group(1) == "kali-desktop":
            ver_m = re.search(r'^version\s*=\s*"([^"]+)"', block, re.MULTILINE)
            if not ver_m:
                _fail("VERSION_INVALID cargo_lock: у kali-desktop нет version")
            return ver_m.group(1)
    _fail("VERSION_INVALID cargo_lock: пакет kali-desktop не найден")


def _read_tauri(repo: Path) -> str:
    data = json.loads((repo / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str):
        _fail("VERSION_INVALID tauri: .version отсутствует в tauri.conf.json")
    return version


def _read_iss(repo: Path) -> str:
    text = (repo / "scripts" / "installer_premium.iss").read_text(encoding="utf-8")
    m = _ISS_RE.search(text)
    if not m:
        _fail("VERSION_INVALID iss: #define AppVersion не найден")
    return m.group(1)


def read_desktop_versions(repo: Path) -> dict[str, str]:
    """Собрать версии всех шести desktop-источников.

    Args:
        repo: Корень репозитория.

    Returns:
        Словарь ключей ``DESKTOP_KEYS`` → строковая версия каждого источника.

    Raises:
        SystemExit: Если любой источник не разбирается (сообщение содержит ключ).
    """
    return {
        "pyproject": _read_pyproject(repo),
        "kernel": _read_kernel(repo),
        "cargo_toml": _read_cargo_toml(repo),
        "cargo_lock": _read_cargo_lock(repo),
        "tauri": _read_tauri(repo),
        "iss": _read_iss(repo),
    }


def read_mobile_version(repo: Path) -> str:
    """Прочитать top-level ``version`` из mobile/pubspec.yaml и провалидировать.

    Args:
        repo: Корень репозитория.

    Returns:
        Строка вида ``X.Y.Z+N`` (numeric build number).

    Raises:
        SystemExit: Если версия отсутствует или не ``X.Y.Z+N``
            ('MOBILE_VERSION_INVALID').
    """
    text = (repo / "mobile" / "pubspec.yaml").read_text(encoding="utf-8")
    m = re.search(r"^version:\s*(\S+)\s*$", text, re.MULTILINE)
    if not m or not _MOBILE_RE.match(m.group(1)):
        got = m.group(1) if m else "<absent>"
        _fail(f"MOBILE_VERSION_INVALID: {got!r} — ожидается X.Y.Z+N")
    return m.group(1)


# ── check ───────────────────────────────────────────────────────────────────
def check(repo: Path) -> str:
    """Проверить единство desktop-версий; вернуть канонический ``VERSION``.

    Args:
        repo: Корень репозитория.

    Returns:
        Канонический ``VERSION`` при полном совпадении desktop-источников.

    Raises:
        SystemExit: При desktop-skew ('VERSION_SKEW' + ключ источника) либо
            невалидной mobile-версии. Mobile != desktop — предупреждение.
    """
    canonical = read_version_file(repo)
    desktop = read_desktop_versions(repo)
    for key in DESKTOP_KEYS:
        if desktop[key] != canonical:
            _fail(
                f"VERSION_SKEW: {key}={desktop[key]!r} != VERSION={canonical!r} "
                f"(источник: {key})"
            )
    mobile = read_mobile_version(repo)
    if mobile.split("+")[0] != canonical.split("-")[0]:
        log.warning(
            "mobile %s отличается от desktop %s (отдельный трек, не fail)",
            mobile, canonical,
        )
    return canonical


# ── sync (writers) ──────────────────────────────────────────────────────────
def _rewrite_toml_version(path: Path, new: str, table: str) -> None:
    """Заменить ровно одну ``version =`` в таблице ``[table]``.

    Raises:
        SystemExit: 'VERSION_SYNC_FAILED', если version-запись в таблице не найдена.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    current = None
    done = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped.strip("[]").strip()
        if not done and current == table and re.match(r"\s*version\s*=", line):
            eol = "\n" if line.endswith("\n") else ""
            out.append(f'version = "{new}"{eol}')
            done = True
            continue
        out.append(line)
    if not done:
        _fail(f"VERSION_SYNC_FAILED: {path.name}: version в [{table}] не найдена")
    path.write_text("".join(out), encoding="utf-8")


def _sync_kernel(repo: Path, new: str) -> None:
    path = repo / "kernel" / "__init__.py"
    text = path.read_text(encoding="utf-8")
    text, n = re.subn(
        r"""(__version__\s*(?::\s*str)?\s*=\s*['"])[^'"]*(['"])""",
        rf"\g<1>{new}\g<2>", text, count=1,
    )
    if n != 1:
        _fail("VERSION_SYNC_FAILED: kernel/__init__.py: __version__ не найден")
    path.write_text(text, encoding="utf-8")


def _sync_cargo_lock(repo: Path, new: str) -> None:
    path = repo / "src-tauri" / "Cargo.lock"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'(\[\[package\]\]\nname = "kali-desktop"\nversion = ")[^"\n]*(")'
    )
    text, n = pattern.subn(rf"\g<1>{new}\g<2>", text, count=1)
    if n != 1:
        _fail("VERSION_SYNC_FAILED: Cargo.lock: блок kali-desktop не найден")
    path.write_text(text, encoding="utf-8")


def _sync_tauri(repo: Path, new: str) -> None:
    path = repo / "src-tauri" / "tauri.conf.json"
    text = path.read_text(encoding="utf-8")
    text, n = re.subn(r'("version"\s*:\s*")[^"]*(")', rf"\g<1>{new}\g<2>", text, count=1)
    if n != 1:
        _fail("VERSION_SYNC_FAILED: tauri.conf.json: .version не найдена")
    path.write_text(text, encoding="utf-8")


def _sync_iss(repo: Path, new: str) -> None:
    path = repo / "scripts" / "installer_premium.iss"
    text = path.read_text(encoding="utf-8")
    m = _ISS_RE.search(text)
    if not m:
        _fail("VERSION_SYNC_FAILED: installer_premium.iss: #define AppVersion не найден")
    old = m.group(1)
    if old != new:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def sync(repo: Path) -> None:
    """Записать ``VERSION`` во все шесть desktop-источников идемпотентно.

    Каждый writer доказывает, что нашёл и заменил ровно ожидаемую запись; при
    отсутствующем anchor — ``VERSION_SYNC_FAILED`` (не ложный success). После
    всех записей — обязательная сверка ``check(repo)``: любой оставшийся skew
    завершится ``VERSION_SKEW``.

    Args:
        repo: Корень репозитория.

    Raises:
        SystemExit: 'VERSION_INVALID' / 'VERSION_SYNC_FAILED' / 'VERSION_SKEW'.
    """
    new = read_version_file(repo)
    _rewrite_toml_version(repo / "pyproject.toml", new, "project")
    _sync_kernel(repo, new)
    _rewrite_toml_version(repo / "src-tauri" / "Cargo.toml", new, "package")
    _sync_cargo_lock(repo, new)
    _sync_tauri(repo, new)
    _sync_iss(repo, new)
    check(repo)  # обязательная пост-сверка: convergence или VERSION_SKEW


# ── manifest ────────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return proc.stdout


def build_manifest(repo: Path, assets: list | None = None, *,
                   strict: bool = False) -> dict:
    """Собрать snapshot (версия, git SHA, dirty, компоненты, timestamp).

    ``strict=False`` — диагностический snapshot: показывает dirty/skew как есть,
    не отказывает (для аудита). ``strict=True`` — release-manifest: отказывает
    при VERSION_SKEW или dirty-дереве, поэтому файл с противоречивыми
    component-версиями не может называться валидным release-manifest.

    Args:
        repo: Корень репозитория.
        assets: Опциональный список ассетов (пробрасывается в манифест как есть).
        strict: Режим release-manifest (fail-closed на skew/dirty).

    Returns:
        Словарь манифеста для сериализации.

    Raises:
        SystemExit: 'VERSION_SKEW' или 'RELEASE_MANIFEST_DIRTY' при ``strict``.
    """
    if strict:
        check(repo)  # skew → VERSION_SKEW ещё до сборки манифеста
    git_sha = _git(repo, "rev-parse", "HEAD").strip()
    dirty = bool(_git(repo, "status", "--porcelain").strip())
    manifest = {
        "version": read_version_file(repo),
        "git_sha": git_sha,
        "git_sha_short": git_sha[:12],
        "dirty": dirty,
        "components": {
            **read_desktop_versions(repo),
            "mobile": read_mobile_version(repo),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if assets is not None:
        manifest["assets"] = assets
    if strict and manifest["dirty"]:
        _fail("RELEASE_MANIFEST_DIRTY: dirty-дерево — release-manifest не создаётся")
    return manifest


# ── semver compare (для burned-version guard) ───────────────────────────────
def _semver_parts(version: str) -> tuple[tuple[int, int, int], list[str] | None]:
    m = _SEMVER_RE.match(version)
    core, _, pre = version.partition("-")
    major, minor, patch = (int(x) for x in core.split("."))
    return (major, minor, patch), (pre.split(".") if (m and pre) else None)


def _cmp_ident(x: str, y: str) -> int:
    """Сравнить два alphanumeric pre-release идентификатора (semver §11).

    Для формы ``<alpha><digits>`` (напр. ``rc10``) с одинаковым буквенным
    префиксом хвостовое число сравнивается ЧИСЛЕННО (``rc10 > rc2``); иначе —
    чисто лексикографически (сохраняет pure-alpha поведение).

    Args:
        x: Первый идентификатор (x != y гарантировано вызывающим).
        y: Второй идентификатор.

    Returns:
        -1 если x<y, 0 если равны, 1 если x>y.
    """
    mx, my = _ALNUM_SPLIT_RE.match(x), _ALNUM_SPLIT_RE.match(y)
    if mx and my and mx.group(1) == my.group(1):
        xi, yi = int(mx.group(2)), int(my.group(2))
        return (xi > yi) - (xi < yi)
    return (x > y) - (x < y)


def _cmp_pre(a: list[str] | None, b: list[str] | None) -> int:
    if a is None and b is None:
        return 0
    if a is None:  # release > prerelease
        return 1
    if b is None:
        return -1
    for x, y in zip(a, b):
        if x == y:
            continue
        xn, yn = x.isdigit(), y.isdigit()
        if xn and yn:
            return -1 if int(x) < int(y) else 1
        if xn != yn:
            return -1 if xn else 1
        return _cmp_ident(x, y)
    return (len(a) > len(b)) - (len(a) < len(b))


def is_valid_semver(value: object) -> bool:
    """True, если ``value`` — строка вида MAJOR.MINOR.PATCH[-prerelease].

    Args:
        value: Проверяемое значение (любого типа — не-строки → False).

    Returns:
        Признак валидного semver.
    """
    return isinstance(value, str) and bool(_SEMVER_RE.match(value))


def compare_semver(a: str, b: str) -> int:
    """Сравнить две semver-строки (-1/0/1) с учётом pre-release-порядка.

    Args:
        a: Первая версия.
        b: Вторая версия.

    Returns:
        -1 если a<b, 0 если равны, 1 если a>b.
    """
    ca, pa = _semver_parts(a)
    cb, pb = _semver_parts(b)
    if ca != cb:
        return -1 if ca < cb else 1
    return _cmp_pre(pa, pb)


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> None:
    """CLI-обёртка: ``check`` | ``sync`` | ``manifest`` на ``REPO_ROOT``.

    Args:
        argv: Опциональные аргументы (по умолчанию — sys.argv[1:]).
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "sync", "manifest", "diagnose"])
    args = parser.parse_args(argv)
    if args.command == "check":
        version = check(REPO_ROOT)
        table = read_desktop_versions(REPO_ROOT)
        for key in DESKTOP_KEYS:
            print(f"  {key:<12} {table[key]}")
        print(f"  mobile       {read_mobile_version(REPO_ROOT)}")
        print(f"OK: {version}")
    elif args.command == "sync":
        sync(REPO_ROOT)  # включает check(); при skew падает до печати ниже
        print(f"synced -> {read_version_file(REPO_ROOT)}")
    elif args.command == "diagnose":
        # Диагностический snapshot: показывает skew/dirty для аудита, НЕ отказывает.
        canonical = read_version_file(REPO_ROOT)
        table = read_desktop_versions(REPO_ROOT)
        skewed = [k for k in DESKTOP_KEYS if table[k] != canonical]
        dirty = bool(_git(REPO_ROOT, "status", "--porcelain").strip())
        print(json.dumps(
            {"canonical": canonical, "components": table,
             "skewed": skewed, "dirty": dirty},
            ensure_ascii=False, indent=2,
        ))
    else:  # manifest — строгий release-manifest (отказ при skew/dirty)
        print(json.dumps(
            build_manifest(REPO_ROOT, strict=True), ensure_ascii=False, indent=2
        ))


if __name__ == "__main__":
    main()
