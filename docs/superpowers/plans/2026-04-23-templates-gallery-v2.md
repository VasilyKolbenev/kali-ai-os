# Templates Gallery v2 — Plan Stub

> Status: STUB. Написан 2026-04-22. Full detail пишется после завершения voice-builder-pilot.

**Goal:** Расширить skill templates с 5 абстрактных (tracker/reminder/monitor/notifier/logger) до 20+ конкретных user-facing для non-tech persona.

**Depends on:** voice-builder-pilot завершён и работает с existing 5 templates.

## Why now (trigger)

Pilot доказал что voice-flow работает. Теперь каждый new template = новый use case доступный за voice. Без gallery non-tech user не знает "что можно".

## Target templates (20+)

**Здоровье:**
- water-tracker — пить воду с напоминалками
- mood-diary — дневник настроения
- meds-reminder — приём лекарств
- sleep-tracker — фиксация сна
- steps-goal — ежедневная цель шагов

**Работа/продуктивность:**
- focus-timer — pomodoro с голосом
- daily-standup — утренний standup prompter
- task-capture — quick task dump голосом
- meeting-notes — конспекты по triggers

**Финансы:**
- expense-tracker — траты голосом
- savings-goal — цель накопления
- crypto-watch — мониторинг курса
- subscription-audit — учёт подписок

**Быт:**
- cooking-timer — многоэтапные таймеры для рецептов
- shopping-list — голосовой список покупок
- plant-care — полив растений с напоминалками
- car-maintenance — ТО автомобиля

**Специализированные (примеры для user personas):**
- bricks-counter (строитель) — счётчик материалов по фото
- patient-diary (врач) — дневник симптомов пациента
- student-schedule (студент) — учебное расписание + напоминалки

## Approach

1. Для каждого template: design questions + tools + config schema + tests
2. Каждый template = self-contained file в `kernel/skill_templates/`
3. UI gallery с фильтрами (персона, категория, популярность)
4. "Remix" button — копия template с голосовой кастомизацией

## Estimate

~1.5–2 дня после pilot готов. 15 templates × 1–1.5 часа design+impl+test.

## Non-goals

- Не всё-в-один-спринте. Выкатывать пачками по 5 штук.
- Не pretending что полное покрытие use cases — это minimum viable gallery.
