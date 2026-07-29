"""F1: у backend в shipping-stage ровно один владелец — stage_composer.

Live-gate 2026-07-29 (Gate B) упал так:

    resource path `..\\dist\\kali-backend` doesn't exist

``src-tauri/tauri.conf.json`` объявлял ресурс ``../dist/kali-backend``, которого
релизный поток НЕ создаёт (премиальный backend собирается в
``dist_premium/kali-backend``), а CI прятал расхождение пустой заглушкой
``New-Item -ItemType Directory -Force dist/kali-backend``. На dev-машине каталог
существовал как остаток старых сборок, поэтому дефект был невидим — сборка на
чистом worktree падала.

Тесты фиксируют, что stale-путь не вернётся и что backend попадает в дистрибутив
только через запечатанный stage.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TAURI_CONF = ROOT / "src-tauri" / "tauri.conf.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
ISS = ROOT / "scripts" / "installer_premium.iss"
STAGE_COMPOSER = ROOT / "scripts" / "release" / "stage_composer.py"

STALE_RESOURCE = "dist/kali-backend"


def _slashes(text: str) -> str:
    """Сравнение путей без зависимости от разделителя."""
    return text.replace("\\", "/")


# ── F1.1/F1.4: tauri не объявляет backend-ресурс ────────────────────────────
def test_tauri_bundle_declares_no_backend_resource() -> None:
    conf = json.loads(TAURI_CONF.read_text(encoding="utf-8"))
    resources = conf.get("bundle", {}).get("resources", [])
    offenders = [r for r in resources if "kali-backend" in _slashes(str(r))]
    assert offenders == [], f"tauri.conf.json снова объявляет backend-ресурс: {offenders}"


def test_tauri_config_has_no_stale_dist_backend_path() -> None:
    assert STALE_RESOURCE not in _slashes(TAURI_CONF.read_text(encoding="utf-8"))


# ── F1.2/F1.4: CI не маскирует расхождение заглушкой ────────────────────────
def test_ci_does_not_stub_the_backend_resource_dir() -> None:
    ci = _slashes(CI_WORKFLOW.read_text(encoding="utf-8"))
    assert STALE_RESOURCE not in ci, "CI снова создаёт заглушку dist/kali-backend"
    assert "Stub backend resource dir" not in ci


def test_ci_does_not_carry_the_masking_comment() -> None:
    # Комментарий объяснял, ЗАЧЕМ нужна заглушка; без заглушки он дезинформирует.
    ci = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "requires the path to exist even for check" not in ci


# ── F1.5: единственный владелец — stage_composer, через sealed stage ────────
def test_installer_ships_only_from_the_sealed_stage() -> None:
    # Единственный Source инсталлятора — запечатанный premium_stage, поэтому
    # backend не может попасть в дистрибутив мимо композитора.
    sources = [line.strip() for line in ISS.read_text(encoding="utf-8").splitlines()
               if line.strip().startswith("Source:")]
    assert sources, "в .iss не найдено ни одной Source-строки — контракт не проверен"
    for line in sources:
        assert _slashes("dist_premium/premium_stage") in _slashes(line), line
        assert STALE_RESOURCE not in _slashes(line), line


def test_stage_composer_is_the_backend_stager() -> None:
    composer = STAGE_COMPOSER.read_text(encoding="utf-8")
    assert 'copytree(inputs["backend"]' in composer, (
        "stage_composer перестал быть тем, кто заносит backend в stage — "
        "контракт единственного владельца надо перепроверить")
