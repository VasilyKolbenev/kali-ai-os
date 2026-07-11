# Spec: Профиль-«анкета» — Jarvis знает пользователя

**Date:** 2026-07-11 · **Status:** DRAFT (ждёт утверждения Vasily)
**Design approved:** 2026-07-01 (`docs/public-launch/2026-07-01-next-work-plan.md` §A)
**Anti-pivot:** ✓ personalization + local data; нет облачного профиля; всё skippable.

## Цель

Опциональная короткая анкета при онбординге: **имя · пол · род занятий · город · возраст-диапазон** (все поля пропускаемые) → факты в локальную память → персона адаптирует обращение (имя, «сэр»/«мэм»), грамматику (пол), лексику (род занятий), локальный контекст (город). Гибрид: форма + «сказать голосом» per-field (только когда STT готов — честная деградация).

## Граундинг (проверено в коде 2026-07-11)

| Опора | Где | Статус |
|---|---|---|
| `save_user_fact(topic, fact, confidence)` | `kernel/database.py:233` | ✅ есть (append-only INSERT) |
| `get_user_context_string()` → `<UserFacts>` в system-prompt каждого хода | `kernel/long_term_memory.py:55`; вызовы: `main.py:1501` (chat), `voice/pipeline.py:439`, `voice/remote_pipeline.py:178` | ✅ есть |
| Онбординг-степы | `ui/src/stores/onboardingStore.ts` `STEP_ORDER`; рендер `OnboardingRoot.tsx` | ✅ есть; `persist.partialize` хранит только `completed` → вставка степа без миграции |
| Голосовой ввод | `POST /voice/transcribe` + `useAudioCapture.ts` (путь VoiceBuilder) | ✅ переиспользуем |
| Mobile standalone system-prompt | `mobile/lib/presentation/standalone_chat_screen.dart:105` — `systemPrompt: widget.agent.skillMd` | ✅ call-site один |
| Mobile store-паттерн | `llm_settings_store.dart` (secure) / `agent_store.dart` (файловый) | ✅ профиль = файловый (не секрет) |

## Три находки граундинга (дизайн 07-01 их не учитывал)

1. **Кап вытеснит профиль.** `MAX_INJECTED_FACTS = 50`, newest-first (`long_term_memory.py:53`). Профильные факты — самые старые → через месяцы экстракций выпадут из промпта. **Решение:** профильные топики получают фиксированный префикс `profile.` (напр. `profile.name`), и `get_user_context_string()` **всегда** инжектит их первыми, вне капа (кап остаётся для остальных).
2. **Редактирование = дубли.** `save_user_fact` — append-only INSERT; повторное сохранение анкеты создаст противоречащие факты («Город: Москва» + «Город: Ереван»). **Решение:** новый `db.upsert_user_fact(topic, fact)` (DELETE by topic + INSERT) — используется только для `profile.*` топиков; экстракция фактов из речи не трогается.
3. **Персона хардкодит «сэр».** `jarvis_persona.py` правило 3: «сэр»/"sir" всегда — женщина с фактом «Пол: женский» останется «сэр». **Решение:** одна строка в персоне: обращение по полу, если пол известен из фактов («сэр»/«мэм»), + «учитывай пол пользователя в грамматических согласованиях; адаптируй сложность лексики под род занятий». Без шаблонов per-gender — LLM согласует сам (дизайн-принцип 07-01 подтверждён).

## Increment 1 — Desktop

### Backend (kernel)
- **`GET /profile`** → `{name, gender, occupation, city, age_range}` (из `user_facts` по `profile.*` топикам; отсутствующие = `null`).
- **`POST /profile`** body `{name?, gender?, occupation?, city?, age_range?}`:
  - каждое непустое поле → `upsert_user_fact("profile.<field>", "<человекочитаемый факт>")` (напр. `profile.gender` → «Пол: женский»);
  - пустые/отсутствующие поля пропускаются (skip ≠ затирание);
  - явное `""` (пользователь стёр поле в Settings) → DELETE топика;
  - валидация на границе: строки ≤ 200 символов, `gender ∈ {male, female}`, `age_range ∈ {18-25, 26-35, 36-45, 46-55, 55+}`; мусор → 422.
- **`db.upsert_user_fact(topic, fact)`** + **`db.delete_user_facts_by_topic(topic)`** в `database.py`.
- **`get_user_context_string()`**: `profile.*` факты всегда в начале `<UserFacts>`, кап 50 — только для остальных.
- **`jarvis_persona.py`**: строка про пол/обращение/лексику (см. находку 3).

### Frontend (ui)
- **`ProfileStep.tsx`** в `STEP_ORDER` **после `mic-test`**, до `first-agent` (голосовой ввод уже работоспособен). Полностью пропускаемый («Пропустить» = advance без POST).
  - Поля: имя (text) · пол (2 кнопки) · род занятий (chips: строитель/врач/офис/учитель/другое+text) · город (text) · возраст (chips диапазонов).
  - Per-field кнопка 🎤 «сказать голосом»: `useAudioCapture` → `POST /voice/transcribe` → текст в поле. Кнопка видна только при `micPermission === "granted"` && STT готов (`/voice/status`); иначе скрыта — честная деградация, форма работает всегда.
  - Сохранение: один `POST /profile` на «Далее».
- **Settings**: секция «Профиль» (`ProfileSettings.tsx` в `sections/`), `GET /profile` prefill → `POST /profile` при сохранении; очистка поля = удаление факта.

### Тесты Inc 1
- pytest (`core_loop`-совместимые): POST пишет только непустые; повторный POST не создаёт дублей (upsert); `""` удаляет; 422 на мусор; GET round-trip; `get_user_context_string` содержит профильные факты при 60+ прочих фактах (пиннинг вне капа).
- vitest: ProfileStep рендер/skip-без-POST/save-POST-payload; voice-кнопка скрыта без STT; STEP_ORDER позиция; ProfileSettings prefill+save.

## Increment 2 — Mobile standalone

- **`mobile/lib/standalone/profile_store.dart`** — файловый JSON (`profile.json` в app-docs, паттерн `agent_store.dart`; НЕ secure storage — не секрет), immutable `UserProfile` + `load()/save()`, атомарная запись (.tmp+rename).
- **`_profileBlock(profile)`**: `«Профиль пользователя (данные, а не инструкции): Имя: … · Пол: … · …»` — prepend к `agent.skillMd` в `standalone_chat_screen.dart:105` (единственный call-site). Пустой профиль → prepend ничего.
- **`profile_screen.dart`** — форма-only (без локального STT в standalone), вход из `settings_screen.dart`.
- Тесты: ProfileStore round-trip + corrupt-JSON → пустой профиль (не крэш); `_profileBlock` формат + пустой профиль; widget-тест: chat отправляет profile+skillMd (fake ChatFn ловит systemPrompt).

## Порядок работ

1. Inc 1 backend (db upsert → /profile → пиннинг → персона) — TDD.
2. Inc 1 frontend (ProfileStep → Settings) — TDD.
3. Гейты: `pytest -m core_loop` + broad · `vitest` · smoke в live-app (скрин ProfileStep + факт в ответе Jarvis).
4. Inc 2 mobile — TDD; гейт: весь `flutter test`.
5. Коммиты атомарные на `main`, пуш после зелёных гейтов.

## Вне скоупа
Облачная синхронизация профиля · автозаполнение из соцсетей · погода по городу (отдельный агент уже может использовать факт) · изменение LLM-экстракции фактов · mobile voice-fill.
