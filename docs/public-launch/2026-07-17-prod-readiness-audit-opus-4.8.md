# KALI: prod-readiness аудит и план исправлений для Opus 4.8

Дата аудита: 2026-07-17  
Ветка и ревизия: main, e3db43c  
Проверенный релизный кандидат: 1.0.0-rc2  
Область: Windows Desktop, Android, iOS, backend, voice pipeline, updater, installer, CI/CD, privacy, лицензии и документация.

## 1. Итоговый вердикт

**Публичную раздачу всех трёх версий сейчас начинать нельзя: NO-GO.**

| Платформа | Текущий статус | Что допустимо после P0 |
|---|---|---|
| Windows Desktop | NO-GO | Закрытая trusted-alpha после чистой пересборки, подписи, проверки startup и отключения небезопасного updater |
| Android | NO-GO | Internal testing в Google Play после release-signing, корректной privacy disclosure и замены placeholder-ресурсов |
| iOS | NO-GO | TestFlight после подписанной сборки на Xcode 26, настройки privacy/local-network и проверки на реальном устройстве |

Основная причина не в количестве новых функций. Текущий риск создают расхождение исходников и раздаваемых бинарников, ненадёжная цепочка обновления, retired-модель Anthropic, ошибочные privacy-утверждения, незавершённые mobile release pipelines и юридически неочищенные voice assets.

Публичный запуск нельзя считать готовым по зелёным unit-тестам. Нужна проверка именно устанавливаемых и подписанных артефактов на чистых устройствах.

## 2. Что было проверено

- Актуальный HEAD и незакоммиченные изменения, история последних rc1/rc2-коммитов.
- Desktop installer, staged backend, свежий backend build, timestamps, SHA-256 и Authenticode.
- Реальные логи установленного приложения из AppData/Roaming/KALI/logs.
- FastAPI lifespan, Tauri startup, Rust proxy, updater и installer scripts.
- Voice pipeline: VAD, wake word, STT, TTS, RVC, prewarm и ownership моделей.
- Active GitHub Actions, а также отдельные неактивные workflow-файлы в каталоге ci.
- Flutter Android/iOS конфигурация, signing, permissions, deep links, privacy и store metadata.
- Лицензии фактически упакованных моделей и FFmpeg binaries.
- Автотесты Python core loop, UI и Flutter; отдельная попытка Rust и voice suites.
- Актуальные официальные требования Tauri, Flutter, Google Play, Apple и Anthropic на 2026-07-17.

## 3. Критические находки

### P0-01. Раздаваемый Windows installer не соответствует актуальному коду

**Доказательства**

- dist_premium/installer/KALI-Premium-Setup-1.0.0-rc2.exe создан 2026-07-15 19:33.
- Свежий backend был собран позднее, а последний TTS fix ebcf981 попал в репозиторий в 21:38.
- В handoff 2026-07-15 текущий installer прямо помечен как DO NOT DISTRIBUTE.
- Установленный backend пишет версию 1.0.0-rc1, хотя имя installer содержит rc2.
- Version source-of-truth расходится: Tauri/Cargo/ISS = rc2, Python package/kernel = rc1, mobile = 0.1.0+1.
- scripts/publish_release.py сверяет только часть desktop-версий и имена артефактов.

**Риск**

Пользователь получает известную старую сборку, а баг-репорты невозможно однозначно связать с исходным кодом.

**Исправление**

1. Ввести один release version source-of-truth и генерацию версий для Python, Cargo, Tauri, Inno Setup, Flutter и manifest.
2. Сделать clean staging: не использовать additive robocopy /E поверх старого premium_stage.
3. Собирать installer только из immutable release staging, созданного в текущем CI run.
4. Генерировать release-manifest с commit SHA, версиями компонентов, SHA-256, размером, build time и toolchain.
5. Запретить publish при dirty tree, version skew, stale timestamps или отсутствии release manifest.

**Критерий приёмки**

- Установленное приложение, About/API/version endpoint, имя installer и release manifest показывают одну версию и commit.
- Clean VM без Python/Rust/Node запускает KALI после одной установки.
- Offline smoke выполняется над тем же staging, из которого создан installer.

### P0-02. Серое окно Desktop вызвано блокирующим startup и долгой готовностью backend

**Доказательства**

- src-tauri/src/lib.rs синхронно вызывает start_backend внутри setup.
- start_backend ждёт готовность Python backend до пяти секунд до запуска Rust/UI.
- kernel/main.py всё ещё await-ит TTS load_models в FastAPI lifespan.
- Реальный startup в логе занимает около 11.6 секунды.
- Voice auto-start и STT prewarm частично вынесены в background, но TTS prewarm и frozen torch pre-import всё ещё влияют на startup.
- VoicePipeline и app.state создают два отдельных SpeechToText instance. Логи показывают две независимые попытки загрузки/failure STT.

**Риск**

Пользователь видит пустое серое окно, считает приложение зависшим, а отсутствие сети или проблемы Hugging Face могут сорвать старт.

**Исправление**

1. Tauri должен немедленно показать shell/splash и запустить Rust API до Python.
2. Python backend запускать неблокирующе; readiness отображать в UI по этапам.
3. Разделить liveness и readiness. Liveness не должен зависеть от загруженных voice-моделей.
4. Все тяжёлые voice-модели загружать через single-flight background coordinator.
5. Убрать сетевые загрузки из runtime release: модели должны быть в подписанном package/cache или скачиваться отдельным управляемым installer step с прогрессом и checksum.
6. Внедрить один shared STT owner вместо VoicePipeline STT плюс app.state STT.
7. При ошибке voice-моделей запускать UI и text mode, показывая понятный degraded status.

**Критерий приёмки**

- Первый визуальный кадр не позднее 1 секунды на поддерживаемом ПК.
- UI интерактивен не позднее 2 секунд и показывает прогресс backend/voice.
- Отсутствие интернета не блокирует запуск.
- Ни одна модель не загружается дважды.
- Voice ready достигается в пределах согласованного SLA и имеет timeout/fallback.

### P0-03. Custom updater не имеет независимой криптографической цепочки доверия

**Доказательства**

- src-tauri/src/backend/updater.rs получает mutable latest.json из main-ветки GitHub.
- SHA-256 бинарника хранится в том же изменяемом manifest.
- После проверки hash загруженный EXE запускается автоматически.
- Отдельная asymmetric signature manifest/artifact не проверяется.

**Риск**

Компрометация GitHub account/repository позволяет заменить installer и его hash одновременно, что превращает updater в удалённое выполнение кода.

**Исправление**

1. До исправления полностью отключить auto-install update в public builds.
2. Предпочтительно перейти на официальный Tauri updater с обязательной signature verification и встроенным public key.
3. Если custom updater сохраняется, подписывать canonical manifest отдельным offline Ed25519 key и вшить только public key в приложение.
4. Дополнительно требовать валидный Authenticode publisher у Windows package.
5. Защитить от downgrade/replay: monotonic version, channel, expiry и minimum supported version.
6. Размещать immutable release assets, не использовать raw main как release control plane.

**Критерий приёмки**

- Изменённый binary, manifest, hash, signature или publisher отвергаются.
- Старый валидно подписанный release не может выполнить downgrade.
- Private signing key отсутствует в репозитории и CI logs.

### P0-04. Desktop и Android signing pipelines fail open

**Доказательства**

- Текущий Windows installer имеет Authenticode status NotSigned.
- scripts/build_installer_premium.bat успешно завершается без certificate.
- При отсутствии signtool signing subroutine пропускает подпись без failure.
- Нет обязательного post-build signtool verify /pa.
- Android Fastlane не передаёт kaliRequireSigning=true.
- android/app/build.gradle.kts может использовать debug signing fallback для release.

**Риск**

Публично распространяется неподписанный Windows EXE либо Android release, фактически подписанный debug key.

**Исправление**

1. Public/release mode должен fail closed без certificate, timestamp server и verification.
2. Добавить signtool verify /pa и проверку ожидаемого publisher subject.
3. Android release всегда собирать с -PkaliRequireSigning=true.
4. Проверять AAB через jarsigner/apksigner/bundletool и сравнивать SHA-256 signing certificate с allowlist.
5. Разделить local debug и CI release scripts, чтобы fallback был технически невозможен.

**Критерий приёмки**

- Unsigned или неверно подписанный artifact не может попасть в publish job.
- Подпись проверяется после скачивания release asset, а не только сразу после build.

### P0-05. Default Anthropic model уже retired

**Доказательства**

- claude-sonnet-4-20250514 жёстко задан в mobile standalone, kernel, UI settings, Rust config и coding agent.
- По официальной документации Anthropic эта модель retired 2026-06-15.

**Риск**

Anthropic path ломается сразу после установки, даже при корректном API key.

**Исправление**

1. Удалить распределённые model constants и создать единый provider model registry.
2. Выбрать актуальный stable default из официального списка Anthropic, не привязывая продукт к Opus как обязательной дорогой модели.
3. Сделать model configurable и валидировать доступность при сохранении settings.
4. Добавить тест, запрещающий retired/deprecated defaults.
5. Ошибки unavailable/model_not_found показывать как actionable provider status, без бесконечных retries.

**Критерий приёмки**

- Новый пользователь с валидным Anthropic key выполняет первый запрос.
- Desktop и mobile показывают одинаковую поддерживаемую model matrix.

### P0-06. Privacy policy и store declarations противоречат фактическому поведению

**Доказательства**

- docs/public-launch/play-store/privacy-policy.md содержит placeholder legal entity, country, contact и URL.
- Документ утверждает, что mobile общается только с desktop и не хранит API keys.
- В standalone mode mobile хранит BYO provider keys в secure storage и напрямую отправляет данные Anthropic/OpenAI.
- Play listing утверждает, что app не работает без desktop, хотя standalone mode существует.
- Утверждение encrypted in transit не универсально: LAN path использует HTTP/WS.

**Риск**

Неверная Data Safety/App Privacy декларация, store rejection и потеря доверия пользователей.

**Исправление**

1. Провести data-flow inventory отдельно для paired LAN и standalone cloud.
2. Переписать privacy policy по фактическому поведению, включая provider subprocessors, retention, deletion, logs, crash reports и contact.
3. Заполнить Google Data Safety и Apple App Privacy из одного versioned data inventory.
4. Убрать placeholders и опубликовать policy на контролируемом HTTPS domain.
5. В приложении дать явный выбор режима и disclosure перед первой отправкой данных внешнему provider.

**Критерий приёмки**

- Каждое сетевое назначение из runtime trace отражено в policy и store forms.
- Нет placeholder и ложных абсолютных утверждений.
- Privacy policy доступна без авторизации и соответствует версии приложения.

### P0-07. Android и iOS пока не являются воспроизводимыми release artifacts

**Доказательства**

- Active Android CI запускает тесты, но не гарантирует signed release AAB.
- Active iOS workflow собирает unsigned Runner.app; signed job закомментирован.
- iOS Fastlane остаётся scaffolding, нет завершённой signing/export конфигурации.
- Android и iOS используют стандартную Flutter launcher icon.
- Placeholder domain/app-store/team-id присутствуют в share/deep-link файлах.

**Риск**

Нет артефакта, который можно безопасно отдать tester group через официальные каналы.

**Исправление**

1. Android: signed AAB, Play Internal testing, versionCode policy, target API 36, release certificate verification.
2. iOS: Xcode 26 и iOS 26 SDK, Distribution certificate/App Store Connect API key, signed archive/IPA, TestFlight.
3. Заменить Flutter icons, launch assets и store screenshots на KALI branding.
4. Удалить или завершить placeholder deep links; не заявлять universal/app links до владения domain.

**Критерий приёмки**

- Android устанавливается из Play Internal testing.
- iOS устанавливается из TestFlight.
- Обе сборки проходят first-run, permissions, pairing, standalone и update regression на реальных устройствах.

### P0-08. Voice package содержит неочищенные коммерческие и IP-риски

**Доказательства**

- Упакованная F5 Russian checkpoint опубликована под CC-BY-NC-4.0.
- В assets/references и документации присутствуют Jarvis/Marvel/Iron Man voice references и признаки стороннего voice source.
- Нет release-level перечня прав на model weights, reference voice и dataset.

**Риск**

Даже бесплатная публичная beta требует юридической оценки; коммерческое использование NC checkpoint блокируется. Имитация узнаваемого персонажа/актёра создаёт отдельный publicity/copyright/trademark риск.

**Исправление**

1. Не раздавать спорные weights/reference audio в public package до письменного clearance.
2. Заменить голос на собственную запись с release/consent и коммерчески совместимый TTS stack.
3. Создать THIRD-PARTY-NOTICES, model card inventory, license manifest и provenance для каждого asset.
4. Удалить marketing/name references, подразумевающие официальную связь с Marvel/JARVIS.
5. Получить юридическую проверку перед monetization.

**Критерий приёмки**

- Для каждого shipped asset известны source, author, license, allowed use и attribution.
- В package нет NC/unknown voice assets без одобренного исключения.

### P0-09. Native community agents исполняются в основном backend process

**Доказательства**

- Frozen desktop импортирует agent.py через spec.loader.exec_module.
- Installer safety gate делает только AST heuristic check.
- Проектная документация сама отмечает, что HTTP sandbox не является security boundary.

**Риск**

Непроверенный bundle получает права пользователя, доступ к токенам, файлам и сети.

**Исправление**

1. Для public beta разрешить только prompt-only skills и curated/signed native agents.
2. Запретить произвольный Python import из community bundles.
3. Native plugins вынести в отдельный least-privilege process с explicit capabilities, IPC allowlist, resource limits и kill switch.
4. Подписывать curated bundles и показывать пользователю permissions до установки.

**Критерий приёмки**

- Неподписанный Python bundle нельзя импортировать или выполнить.
- Security test доказывает отсутствие доступа к backend secrets и произвольной файловой системе.

## 4. Важные P1-находки

### P1-01. LAN pairing token передаётся по cleartext

Android network security config разрешает cleartext, а LAN WebSocket token находится в query string. Проверка private IPv4 уменьшает поверхность, но на общей Wi-Fi сети token можно перехватить и повторно использовать.

Для trusted alpha требуется честное disclosure, короткоживущая сессия, rotation/revoke и запрет логирования query. Для public release нужен TLS/authenticated pairing protocol либо иной доказуемо защищённый локальный transport.

### P1-02. CI не является release gate

- Ruff и mypy пропускаются из-за накопленных ошибок.
- Два security-теста DNS/SSRF исключены.
- Flutter analyze не запускается; локально найдено 21 issue, включая 3 warning.
- Rust test не воспроизвёлся: ort-sys загрузил native ONNX binary из внешнего CDN.
- Cargo build не везде использует --locked; ort rc.10 range разрешил rc.12.
- Flutter action использует floating stable channel.

Нужно зафиксировать toolchains, exact native dependencies, cargo --locked, uv lock validation, Flutter analyze --fatal-infos или согласованный baseline, dependency cache/checksums и SBOM.

### P1-03. iOS local-network/privacy/universal-link configuration незавершена

Нет завершённого NSLocalNetworkUsageDescription, associated domains entitlement, production apple-app-site-association и app-specific PrivacyInfo.xcprivacy. ATS/local networking нужно проверить на реальном iOS 26 с минимально узким исключением, а privacy manifests всех SDK — в итоговом archive privacy report.

### P1-04. Android App Links и public domain — placeholders

Android принимает только custom kali scheme. assetlinks.json содержит placeholder fingerprint; public domain не подтверждён. До владения HTTPS domain оставить claim выключенным. После — добавить verified App Link, production fingerprint и CI verification.

### P1-05. Логи зашумлены и не дают понятного user-facing состояния

- 329 ConnectionResetError WinError 10054.
- Частый polling /health и /crash/status засоряет stdout.
- 12 ответов 429 от исчерпанной OpenAI quota.
- Есть input overflow и voice failures.

Нужно снизить polling, обрабатывать disconnect/cancellation как штатное событие, ввести structured rotating logs с redaction, correlation id и diagnostics export. Provider quota — пользовательская конфигурация, но UI должен остановить retry storm и показать точное действие.

### P1-06. Mobile branding и release metadata не готовы

Обе mobile платформы используют Flutter default icon. Listing, privacy URL, app-store URL, screenshots и часть readme содержат placeholders или устаревшие утверждения. Это не crash-баг, но блокирует публичное доверие и store review.

### P1-07. Python core test пропускает background notification failure

Core loop: 13 passed, но background thread сообщил Shell_NotifyIconW failed, а test остался зелёным. Background exceptions должны попадать в test result; notification subsystem обязан иметь observable delivery/fallback.

### P1-08. Voice reliability ещё не имеет release SLA

В логах есть повторные STT downloads/failures, wake false/no-speech history, input overflow и тяжёлый first load. Voice suite завис после части тестов. Нужны bounded timeout, isolated test IDs, реальный audio corpus, false-accept/false-reject метрики и latency p50/p95.

## 5. Что уже выглядит здоровым

- UI test suite: 173 passed, 1 skipped.
- Flutter tests: 155 passed.
- Python core-loop mark: 13 passed.
- Android cleartext path дополнительно ограничивается private IPv4 checks.
- Фактически упакованный FFmpeg собран без x264/x265 и сообщает LGPL v3-or-later; старое утверждение roadmap о GPL не подтверждается бинарником.
- Silero VAD текущего official repository лицензирован MIT.

Эти результаты полезны, но не отменяют artifact-level и signing blockers.

## 6. План работ для модели-разработчика Opus 4.8

### Обязательные правила выполнения

1. Работать от актуального HEAD, а не от dist, старых roadmap и handoff assumptions.
2. Не добавлять новые продуктовые функции. Цель — release correctness, security, installability и observability.
3. Один логический P0/P1 task — один небольшой commit с тестами и evidence.
4. Не удалять пользовательские незакоммиченные изменения и не переписывать историю.
5. Любой release/security gate делать fail closed.
6. Не отмечать задачу выполненной по source-level тестам: требуется проверка реального installer/AAB/IPA.
7. В начале каждого task зафиксировать reproduction, после — приложить command, output summary, artifact hash и test evidence.
8. Если документация спорит с кодом или runtime trace, источником истины считать проверенный runtime; документацию исправить.

### Phase 0. Зафиксировать baseline и остановить неверную раздачу

**Задача OPUS-001: Release freeze**

Файлы: dist_premium/installer/README.txt, docs/public-launch, scripts/publish_release.py.

- Пометить текущий rc2 installer как internal/stale и исключить из publish.
- Создать machine-readable release-status с distributable=false и причиной.
- Обновить README/CHANGELOG, убрать инструкции про старые 0.1/0.2 installers.

Acceptance: publish script отказывается публиковать текущий artifact.

**Задача OPUS-002: Version source-of-truth**

Файлы: pyproject.toml, kernel/__init__.py, src-tauri/Cargo.toml, src-tauri/tauri.conf.json, scripts/installer_premium.iss, mobile/pubspec.yaml, scripts/publish_release.py.

- Создать scripts/release/version.py или эквивалентный генератор/checker.
- Версия и build number должны генерироваться/проверяться, а не редактироваться вручную в шести местах.
- Release manifest должен включать git SHA и dirty flag.

Acceptance: единая команда version-check падает при искусственном skew.

### Phase 1. Исправить Desktop startup и собрать один корректный package

**Задача OPUS-101: Non-blocking desktop boot**

Файлы: src-tauri/src/lib.rs, src-tauri/src/backend/process.rs, desktop startup UI.

- Убрать backend readiness wait из Tauri setup.
- Сразу запускать визуальный shell и Rust proxy.
- Передавать typed startup states: shell_ready, rust_ready, python_starting, python_ready, voice_loading, voice_ready, degraded, failed.
- Добавить retry/restart без создания второго backend process.

Acceptance: first paint <=1s; UI не становится серым при 30-секундной искусственной задержке backend.

**Задача OPUS-102: Lifespan без тяжёлого voice prewarm**

Файлы: kernel/main.py, kernel/voice/pipeline.py, STT/TTS loaders.

- Оставить в lifespan только быстрые и детерминированные initialization steps.
- Ввести единый async single-flight ModelCoordinator.
- Убрать второй STT instance; внедрить dependency/shared owner.
- Не делать torch.hub/Hugging Face network call при каждом startup.
- Добавить timeout, cancellation и degraded mode.

Acceptance: /live отвечает <=1s; /ready для text mode <=3s; voice readiness независима.

**Задача OPUS-103: Clean frozen build and stage**

Файлы: scripts/build_installer_premium.bat, PyInstaller specs, scripts/frozen_smoke.py.

- Создавать новый staging каталог с уникальным build id.
- Не накладывать файлы поверх старого stage.
- Явно копировать models/cache/license assets по manifest.
- Smoke запускать из exact stage, затем из установленного clean VM.
- Проверить полный offline startup.

Acceptance: две clean builds из одного commit имеют объяснимый manifest; удалённый source asset не остаётся в stage.

### Phase 2. Закрыть update/signing supply chain

**Задача OPUS-201: Windows release signing**

- Signing certificate обязателен в release mode.
- Timestamp обязателен.
- После build выполнить signtool verify /pa и publisher allowlist.
- Сохранить signed hash и verification report.

Acceptance: отсутствие cert/signtool/timestamp завершает job ошибкой.

**Задача OPUS-202: Secure updater**

Файлы: src-tauri/src/backend/updater.rs, tauri config, release workflow.

- Временно отключить auto-execution custom updater.
- Мигрировать на Tauri signed updater либо реализовать независимую signed manifest chain.
- Добавить tamper, wrong-key, replay, downgrade и expired-manifest tests.

Acceptance: hash, размещённый рядом с подменённым EXE, недостаточен для acceptance.

**Задача OPUS-203: Reproducible dependency gate**

- Exact-pin критичные rc dependencies, включая ort.
- Cargo использовать с --locked.
- Убрать неявную native binary download из test/build либо закрепить checksum и mirror/cache.
- Генерировать SBOM для Python, Rust, Node, Flutter и packaged models.

Acceptance: clean CI build не зависит от floating prerelease/CDN state.

### Phase 3. Исправить provider, privacy и legal blockers

**Задача OPUS-301: Current provider model registry**

- Централизовать model defaults.
- Заменить retired Anthropic model актуальной поддерживаемой моделью.
- Синхронизировать desktop/mobile/UI.
- Добавить capability validation и deprecation test.

Acceptance: smoke с тестовым Anthropic account проходит; retired ID отсутствует в runtime defaults.

**Задача OPUS-302: Data map and truthful privacy**

- Снять runtime network trace для paired/standalone/crash/update paths.
- Обновить privacy policy, Data Safety draft и App Privacy draft.
- Добавить first-run disclosure и provider links.
- Проверить redaction API keys, tokens, query strings и user text из logs.

Acceptance: policy-to-code review не находит необъявленного data destination.

**Задача OPUS-303: Voice and third-party rights**

- Создать release asset inventory с SPDX/license/provenance.
- Исключить CC-BY-NC и unknown/character voice assets из public build.
- Подключить юридически очищенный KALI voice.
- Добавить LICENSE, NOTICE и THIRD-PARTY-NOTICES в installer и About.

Acceptance: legal reviewer может проверить каждый shipped binary/model/audio asset.

**Задача OPUS-304: Community bundle containment**

- Для beta выключить arbitrary native Python bundles.
- Оставить curated signed allowlist и prompt-only import.
- Добавить explicit permission review и negative security tests.

Acceptance: malicious sample bundle не выполняет import-time code.

### Phase 4. Android Internal testing

**Задача OPUS-401: Release AAB**

Файлы: mobile/android/app/build.gradle.kts, mobile/android/fastlane/Fastfile, active GitHub workflow.

- Require signing property в release lane.
- Target Android API 36 для загрузок после 2026-08-31.
- Зафиксировать Flutter 3.44.0/toolchain.
- Запустить flutter analyze, test и build appbundle.
- Проверить certificate и AAB через bundletool.

Acceptance: AAB загружается только в Play Internal testing и подписан production upload key.

**Задача OPUS-402: Android privacy/network/deep links**

- Убрать blanket cleartext или сузить его до обоснованного pairing path.
- Ввести token rotation, short TTL, revoke и query redaction.
- Удалить placeholder assetlinks либо настроить owned domain и verified App Links.
- Проверить permissions RECEIVE_BOOT_COMPLETED/notifications: удалить ненужные либо документировать фактическое использование.

Acceptance: security review shared-Wi-Fi сценария и Play pre-launch report без blocker.

**Задача OPUS-403: Android release presentation**

- Заменить Flutter icon/launch assets.
- Завершить listing, screenshots, privacy URL, support URL.
- Удалить ложное утверждение о невозможности standalone mode.

Acceptance: internal listing не содержит placeholder и соответствует runtime.

### Phase 5. iOS TestFlight

**Задача OPUS-501: Signed iOS distribution**

- Выполнять archive на macOS с Xcode 26 и iOS 26 SDK.
- Настроить App Store Connect API key, bundle id, profiles и ExportOptions.
- Загружать build в TestFlight через Fastlane/official tooling.

Acceptance: clean TestFlight install на физическом iPhone.

**Задача OPUS-502: Local network, ATS and privacy**

- Добавить точное NSLocalNetworkUsageDescription.
- Настроить минимально необходимый ATS/local networking exception.
- Добавить PrivacyInfo.xcprivacy по фактическим required-reason APIs/data.
- Проверить archive privacy report и manifests всех SDK.

Acceptance: pairing работает на iOS 26; App Store validation не выдаёт privacy/network blocker.

**Задача OPUS-503: Universal links and iOS presentation**

- До владения domain не заявлять universal links.
- После владения: associated-domains entitlement и production AASA с реальным Team ID.
- Заменить Flutter icon, placeholder store URL и screenshots.

Acceptance: TestFlight build открывает verified link и не содержит placeholder.

### Phase 6. Reliability gates и controlled beta

**Задача OPUS-601: Voice quality gate**

- Найти hanging voice test по одному test ID с timeout.
- Добавить curated RU audio corpus: quiet/noisy/far-field/interruptions.
- Зафиксировать wake false accept/reject, STT WER proxy, first-response latency, TTS start p50/p95 и input overflow.
- Не загружать одну модель дважды.

Acceptance: согласованный SLA выполняется на minimum и recommended hardware.

**Задача OPUS-602: Observability**

- Structured rotating logs, redaction, component/version/build id.
- Уменьшить health polling и штатно подавлять disconnect errors.
- Diagnostics export по явному действию пользователя.
- Background thread/task exceptions должны проваливать tests или попадать в error channel.

Acceptance: 30-минутный session не создаёт error storm; support bundle не содержит secrets.

**Задача OPUS-603: Full CI release gate**

- Вернуть ruff/mypy через baseline debt plan, не оставлять вечный skip.
- Вернуть DNS/SSRF tests.
- Rust test/build --locked.
- UI test/build.
- Flutter analyze/test/release builds.
- Artifact signature/install/offline smoke.

Acceptance: publish job зависит от всех gates и не имеет manual bypass без audit record.

## 7. Обязательная матрица release verification

### Windows Desktop

    uv run pytest -m core_loop
    uv run pytest --timeout=120
    uv run ruff check .
    uv run mypy kernel
    cargo test --manifest-path src-tauri/Cargo.toml --locked
    npm --prefix ui test -- --run
    npm --prefix ui run build
    python scripts/frozen_smoke.py --offline --stage <exact-release-stage>
    signtool verify /pa <installer.exe>

Дополнительно:

- Clean Windows 11 VM без dev tools.
- Offline first boot.
- Online first boot с пустым model cache.
- Нет серого окна и duplicate backend.
- Install, upgrade, rollback rejection, uninstall и retained user data.
- Standard user без admin после установки.

### Android

    flutter pub get
    flutter analyze
    flutter test
    flutter build appbundle --release -PkaliRequireSigning=true
    bundletool validate --bundle <release.aab>
    jarsigner -verify -verbose -certs <release.aab>

Дополнительно:

- Play Internal testing install.
- Android API 24 minimum и API 36 current target/device matrix.
- Permission denial/retry.
- Pairing на private LAN, hostile/shared Wi-Fi review.
- Standalone provider error/quota/offline states.
- Deep-link import consent и malicious payload tests.

### iOS

Выполнять на macOS/Xcode 26:

    flutter analyze
    flutter test
    flutter build ipa --release
    codesign --verify --deep --strict <Runner.app>
    xcrun altool/notary-equivalent App Store validation via current supported workflow

Дополнительно:

- Physical iPhone с iOS 26 и поддерживаемым minimum iOS.
- TestFlight install, microphone/local-network permissions.
- Pairing, background/foreground, network change, provider quota/offline.
- Archive privacy report и App Store Connect validation.

## 8. Definition of Done перед первой внешней раздачей

Release можно отдать коллегам и друзьям только если одновременно выполнено:

- Один version/commit отображается во всех компонентах и manifest.
- Артефакт создан после последнего source commit из clean immutable stage.
- Windows installer подписан и проверен; Android/iOS распространяются через official test channels.
- Startup не блокирует UI и работает offline в degraded text mode.
- Runtime не скачивает критичные модели без consent/progress/checksum.
- Updater имеет независимую signature chain либо отключён.
- Retired model IDs отсутствуют.
- Privacy policy, Data Safety и App Privacy соответствуют network trace.
- Voice/model/assets имеют разрешённые для distribution права.
- Community native code не исполняется без настоящей sandbox/allowlist.
- Все platform gates зелёные на clean devices.
- Известные P1/P2 перечислены в release notes; для P0 нет accepted risk.

## 9. Рекомендуемый порядок и параллельность

Критический путь:

1. OPUS-001/002.
2. OPUS-101/102/103.
3. OPUS-201/202/203.
4. OPUS-301/302/303/304.
5. OPUS-401..403 и OPUS-501..503 параллельно.
6. OPUS-601..603.
7. Clean-device release candidate verification.

Можно параллелить Android и iOS после фикса version/privacy/model registry. Нельзя финализировать installer до startup, signing и asset-license cleanup. Нельзя включать updater до завершения cryptographic tests.

Человеческие blockers, которые модель не может решить сама:

- Windows code-signing certificate.
- Google Play Console account/upload key и final Data Safety approval.
- Apple Developer account, App Store Connect access, certificates/profiles и macOS runner.
- Владение public HTTPS domain.
- Юридическое одобрение voice/model/IP assets и текстов policy.
- Реальные устройства и clean VM для acceptance.

## 10. Проверенные актуальные официальные источники

- Tauri Updater: подписи обновлений обязательны и не отключаются: https://v2.tauri.app/plugin/updater/
- Flutter release notes, актуальная stable 3.44.0: https://docs.flutter.dev/release/release-notes
- Flutter supported platforms, Android 24-36 и iOS 13-26: https://docs.flutter.dev/reference/supported-platforms
- Flutter Android release: https://docs.flutter.dev/deployment/android
- Flutter iOS release: https://docs.flutter.dev/deployment/ios
- Google Play target API: с 2026-08-31 новые apps/updates должны target Android 16/API 36: https://support.google.com/googleplay/android-developer/answer/11926878?hl=en-GB_ALL
- Google Play Data Safety: https://support.google.com/googleplay/android-developer/answer/10787469?hl=en
- Google Play User Data policy: https://support.google.com/googleplay/android-developer/answer/17105854?hl=en
- Android verified App Links: https://developer.android.com/training/app-links/about
- Android App Links verification: https://developer.android.com/training/app-links/verify-applinks
- Apple upcoming requirements: с 2026-04-28 upload требует Xcode 26 и iOS 26 SDK: https://developer.apple.com/news/upcoming-requirements/
- Apple privacy manifests: https://developer.apple.com/documentation/bundleresources/privacy-manifest-files
- Apple ATS: https://developer.apple.com/documentation/security/preventing-insecure-network-connections
- Apple local network permission: https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSLocalNetworkUsageDescription
- Apple associated domains: https://developer.apple.com/documentation/xcode/supporting-associated-domains
- Apple App Privacy: https://developer.apple.com/app-store/app-privacy-details/
- Anthropic current models: https://platform.claude.com/docs/en/about-claude/models/overview
- Anthropic model deprecations: https://platform.claude.com/docs/en/about-claude/model-deprecations
- F5 Russian checkpoint license CC-BY-NC-4.0: https://huggingface.co/Misha24-10/F5-TTS_RUSSIAN
- Silero VAD official MIT repository: https://github.com/snakers4/silero-vad

## 11. Evidence summary текущего аудита

- Windows installer SHA-256: E0A0B2A395DD5C1D6A42ED82E235AD6A7CB9768409D71F70ED0CC91E5C5B5C1A.
- Windows installer Authenticode: NotSigned.
- Реальный backend startup: примерно 11.6 секунды.
- ConnectionResetError в проверенном session log: 329.
- OpenAI 429 в проверенном session log: 12; это состояние quota/config, но UX retry требует исправления.
- UI: 173 passed, 1 skipped.
- Flutter: 155 passed; analyze — 21 issue, включая 3 warning.
- Python core loop: 13 passed; обнаружен нефатальный background Shell_NotifyIconW failure.
- Targeted voice suite не завершилась штатно после части тестов.
- Rust selected tests не стартовали из-за внешней загрузки ort-sys native binary; это build reproducibility gap, а не подтверждённый Rust test failure.

Этот документ заменяет старые launch readiness assumptions там, где они противоречат HEAD, текущим binaries, runtime logs или официальным требованиям на 2026-07-17.
