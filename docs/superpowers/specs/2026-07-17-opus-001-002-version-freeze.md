# Spec: OPUS-001 release-freeze + OPUS-002 version source-of-truth

Дата: 2026-07-17. Ветка: `release/phase-a-desktop-alpha`. Фаза A, блок 1 (чистый guard/tooling, рантайм не трогаем).
Источник истины: `docs/public-launch/2026-07-17-prod-readiness-audit-opus-4.8.md` (P0-01), session-contract.

## Проблема (воспроизведено на HEAD e3db43c)
1. **Version skew ×3:** pyproject/kernel = `1.0.0-rc1`; Cargo.toml/Cargo.lock/tauri.conf/iss = `1.0.0-rc2`; pubspec = `0.1.0+1`. Правится вручную в ≥6 местах.
2. **`publish_release.validate_versions`** проверяет только `tauri==cargo==iss` + наличие exe. НЕ проверяет: pyproject, kernel/__init__, Cargo.lock, pubspec, git dirty/HEAD, staleness артефакта, frozen-hash, signing, release-status.
3. **Нет machine-readable release-status** — publish невозможно заблокировать декларативно.
4. **README.txt устарел** (`0.2.0-beta`), содержит инструкции про старые installer.
5. **Frozen stale rc2** (`E0A0B2A3…5C5B5C1A`, NotSigned, собран до TTS-фикса) может быть опубликован текущим скриптом.

## OPUS-002 — единый version source-of-truth
Новый `scripts/release/version.py` (pure file IO, без сети, schema-валидация на границах).

**Канонический источник:** файл `VERSION` в корне репо — одна строка, desktop release-версия (semver с опц. pre-release, напр. `1.0.0-rc3`).

**Desktop-family (обязана == VERSION):** pyproject `[project].version` · `kernel/__init__.py __version__` · `src-tauri/Cargo.toml [package].version` · `src-tauri/Cargo.lock` (запись пакета `kali-desktop`) · `src-tauri/tauri.conf.json .version` · `scripts/installer_premium.iss #define AppVersion`.

**Mobile-family (отдельный трек):** `mobile/pubspec.yaml version` валидируется как корректный `X.Y.Z+N` (внутренняя валидность + монотонный build number), НЕ обязана равняться desktop. Расхождение desktop-трека — hard fail; невалидная mobile-версия — hard fail; mobile≠desktop — предупреждение, не fail (документируется).

**Команды:**
- `check` → таблица версий; exit 1 при desktop-skew или невалидной mobile-версии. (Сейчас реальный skew → сразу red.)
- `sync` → записать `VERSION` во все desktop-источники идемпотентно (устраняет ручное редактирование 6 мест).
- `manifest` → JSON: `version`, git SHA (short+full), `dirty` (bool), per-component versions, ISO timestamp, toolchain. Пишется в release manifest, потребляется publish-guard.

## OPUS-001 — release-freeze
**`release-status.json`** (корень репо), machine-readable:
```json
{
  "distributable": false,
  "reason": "stale rc2 предшествует STT/TTS-фиксам; NotSigned; version skew rc1/rc2/0.1.0",
  "frozen_artifacts": [
    {"name": "KALI-Premium-Setup-1.0.0-rc2.exe",
     "sha256": "E0A0B2A395DD5C1D6A42ED82E235AD6A7CB9768409D71F70ED0CC91E5C5B5C1A",
     "why": "DO-NOT-DISTRIBUTE"}
  ],
  "as_of": "2026-07-17",
  "requirements_for_distributable_true": [
    "single version+commit во всех компонентах", "signed Authenticode",
    "artifact собран после последнего commit из clean stage", "updater signed/disabled",
    "retired model IDs отсутствуют", "privacy/legal закрыты"
  ]
}
```

**Publish-guard** (`publish_release.py`): отказать при ЛЮБОМ:
- `release-status.distributable != true`;
- git tree dirty по release-relevant путям (version-источники, releases/, dist_premium/installer/);
- version skew (делегировать `version.py check`);
- SHA256 артефакта совпадает с любым `frozen_artifacts[].sha256`;
- mtime артефакта старше времени коммита HEAD (stale);
- отсутствует release manifest.
Все проверки — **до** любого сетевого/`gh`/`git push` действия. Fail-closed.

**README.txt:** заменить устаревший `0.2.0-beta` контент на текущий freeze-notice + принцип «пользователь запускает только `Setup.exe`, backend — внутренний компонент».

## Тесты (TDD — красные на текущем коде)
`tests/scripts/test_release_version.py`:
- `test_check_fails_on_desktop_skew` — фикстура-репо rc1/rc2 → exit 1.
- `test_check_passes_when_synced`.
- `test_sync_writes_all_desktop_sources` — после sync `check` зелёный; каждый источник == VERSION.
- `test_manifest_has_git_sha_and_dirty`.
- `test_invalid_mobile_version_fails`.
- `test_mobile_diff_from_desktop_warns_not_fails`.

`tests/scripts/test_publish_guard.py`:
- `test_publish_refuses_when_not_distributable`.
- `test_publish_refuses_on_frozen_hash`.
- `test_publish_refuses_on_version_skew`.
- `test_publish_refuses_on_stale_artifact` (mtime < HEAD commit time).
- `test_publish_refuses_when_dirty_tree`.
- `test_publish_proceeds_when_all_green` (fake gh/git, guard пройден).

**Мутационный критерий:** удаление любой отдельной проверки guard → ровно один тест краснеет. Существующие 7 тестов `test_publish_release.py` остаются зелёными.

## Acceptance
- `version.py check` падает при искусственном skew и на текущем реальном skew.
- `publish_release` отказывается публиковать текущий frozen rc2 (по hash И по distributable=false).
- Существующие тесты не сломаны; core_loop 13 зелёный.

## Rollback
Новые файлы (`VERSION`, `version.py`, `release-status.json`, 2 тест-файла) — удаляемы. Правки `publish_release.py` — аддитивный guard в начале `main`, revert одного коммита. `sync` идемпотентен, значения версий в git-истории.

## Owner-gate
- Канонический `VERSION` value: предлагается `1.0.0-rc3` (монотонно выше сожжённого rc2, ясно отличается от frozen). Mobile остаётся `0.1.0+1` (трек Phase C). Обратимо.

---

## HARDENED (post adversarial-review, 2026-07-17)

Разрешённые решения:
- Frozen SHA `E0A0B2A3…5C5B5C1A` перехеширован в этой сессии (VERIFY STATE) — byte-correct.
- git гарантирован в publish-env (скрипт уже вызывает git) → fail-closed на git-ошибке.
- `VERSION = 1.0.0-rc3`; `burned_versions = ["1.0.0-rc1","1.0.0-rc2"]`.
- Mobile: только format-валидация `X.Y.Z+N` (монотонность build снята — stateless tool не может её проверить).
- **sync НЕ запускается в этом блоке** — реальные источники остаются skewed, convergence при пересборке (A3/A8). Integration-тест фиксирует текущий skew как RED.
- Build-manifest путь: `dist_premium/installer/release-manifest.json` (генерируется `version.py manifest` при сборке; отсутствует сейчас → publish fail-closed).

Обязательные усиления guard (fail-closed, mutation-provable, каждый `_fail` с reason-token):
1. **FROZEN_HASH**: `casefold()` обе стороны + strip `0x`/whitespace; хешировать КАЖДЫЙ asset (exe + все .bin) по контенту, не по имени/`assets[0]`; `Path.resolve()` симлинки, reject вне `DIST_DIR`.
2. **NOT_DISTRIBUTABLE**: `isinstance(v, bool) and v is True`; всё иное (missing/'true'/0/1/null) → fail. Читать из `REPO_ROOT`, не cwd/argv.
3. **STATUS_MISSING**: отсутствие/битый JSON release-status → fail (не свопать в proceed; guard НЕ внутри `flip_manifest` try/except).
4. **Guard первым в `main()`**, до любого gh/git-push; сам guard только read-only (stat/hash/`git status`/`rev-parse`/`git log`).
5. **ALL-OF**: frozen/dirty/staleness/skew/manifest выполняются безусловно (не short-circuit при distributable=true).
6. **frozen_artifacts non-empty** при distributable=false, иначе fail.
7. **BURNED_VERSION**: refuse при version ∈ burned_versions ИЛИ semver ≤ rc2 (rebuilt-rc2 с новыми байтами).
8. **DIRTY_TREE**: явный список release-путей (6 источников + VERSION + release-status.json + releases/ + dist_premium/installer/); tracked — diff vs HEAD; gitignored installer — прямой stat; git non-zero → fail-closed; правка doc/ не триггерит.
9. **MANIFEST_MISSING/MISMATCH**: manifest.version==VERSION, git_sha==HEAD, dirty==false, asset sha256==пересчитанный.
10. **STALE_ARTIFACT**: committer-date (`%cI`, не author) → UTC-epoch обе стороны; документировать как слабый сигнал (парен с hash+dirty).
11. **OPUS-002 парсинг**: VERSION `utf-8-sig`+strip, reject empty/multiline/невалидный semver; pyproject via `tomllib` `[project].version` (fail на dynamic/absent); Cargo.lock — только блок `[[package]] name="kali-desktop"` (ловушка: `version = 4` на стр.3 + 639 version-строк); tauri `.version`; iss анкер `#define AppVersion`; kernel regex толерантен к кавычкам/аннотации, fail на отсутствие; sync .iss обновляет и `#define`, и stale-комментарии.
12. **Reason-tokens** во всех `_fail` для mutation-provability; refuse-тесты делят `_green_baseline()` и возмущают одну ось.

Финальный тест-лист (≈28 кейсов) — из synthesis workflow, в `tests/scripts/test_release_version.py` и `tests/scripts/test_publish_guard.py`.
