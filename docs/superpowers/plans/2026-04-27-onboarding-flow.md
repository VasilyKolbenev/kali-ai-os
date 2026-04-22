# Onboarding Flow — Plan Stub

> Status: STUB. Создан 2026-04-22. TIER 1 BLOCKER для раздачи non-tech friends.

**Goal:** 5-шаговый flow за ≤2 минуты от первого запуска до рабочего агента. Non-tech user открывает KALI → через 120 секунд у него работает первый агент и он понимает как создать новые.

**Без этого:** 80%+ churn на Day 1 — открыл, не понял, закрыл.

## Depends on

- **holographic-design-tokens** — чтобы onboarding сразу шёл в финальном визуале
- **voice-builder-pilot** — шаг 4 использует builder flow для создания первого агента

## The 5 steps

### Step 1 — Welcome (10 сек)
- Full-screen hero: **"Я — KALI. Помогу тебе превратить голос в AI-агентов."**
- Pulsing orb (из design tokens)
- Subtle JARVIS boot animation: "Инициализация... Все системы в норме."
- Кнопка "Поехали" / "Познакомимся"

### Step 2 — API key setup (40 сек)
- "Чтобы я думал, нужен ключ от мозга. Выбери:"
- 4 cards: **OpenAI** / **Anthropic** / **Google** / **DeepSeek**
- Для выбранного: **встроенное 30-сек видео** где дают ключ (iframe или locally-bundled mp4)
- Input field + кнопка **"Проверить"** — реальный тест вызов с real-time feedback ("Проверяю... ✓ Ключ работает")
- Skip option ("У меня нет ключа, хочу только голос") → переход в text-only demo mode

### Step 3 — Mic + voice test (20 сек)
- Запрос на mic permission (OS dialog)
- "Скажи 'Джарвис, привет'"
- Live STT indicator — видно что записывается
- JARVIS отвечает голосом на основе wizard-selected provider
- "Отлично. Слышу тебя хорошо."

### Step 4 — Первый агент за 60 сек (60 сек)
- **Магический момент.** Это главное.
- JARVIS: "Давай сделаем первого агента. Какую задачу хочешь автоматизировать?"
- 5 pre-filled examples как chips: "напомнить пить воду" / "дневник настроения" / "трекер трат"
- User либо говорит, либо выбирает chip
- Переход в voice-builder-pilot flow (Chunk 3 из плана pilot)
- Когда агент deployed — JARVIS озвучивает: "Готово. Твой первый агент работает."

### Step 5 — Landing в Цифровой статус (10 сек)
- Fade-out onboarding
- Fade-in Цифровой статус с уже одним активным агентом в списке
- Highlight: "Вот твой JARVIS. Говори или пиши — я работаю."
- Optional: pointer-tooltip на mic icon "Говори сюда в любой момент"

## Out of scope

- **Multi-language UI** (пока RU+EN, остальные позже)
- **Cloud account creation** (нет KALI Cloud пока)
- **Payment flow для Pro tier** (отдельный план)
- **Tutorial videos** — только встроенная mic-test и demo agent, без learning mode
- **Import from other tools** — ни Cursor/Raycast config migration, ни Claude Desktop settings

## Risks

- **Mic permission denied** — fallback to text mode, не block flow
- **API key invalid** — clear error + retry, не dead-end
- **Voice test fails** (mic broken / quiet) — show transcript anyway + option "Skip voice"
- **Первый агент fails deploy** — rollback clean, retry option, или alternative text-only demo
- **User skip onboarding** — Settings → "Пройти onboarding заново" option

## Success criteria

- 5 non-tech users (без пред-подготовки) проходят весь flow за ≤2 мин без помощи
- Agent deployed в конце у 90%+ users
- D7 retention среди прошедших onboarding vs skipped — delta ≥+25%
- Explicit "Skip" нажат <20% users (если больше — слишком длинно)

## Estimate

3-4 дня соло. Pre-requires design-tokens + voice-builder-pilot.

## What we lose by shipping without it

Каждый друг-тестер:
1. Открывает → пустой экран
2. Не понимает куда смотреть
3. Попытается что-то сказать → тишина (нет API key)
4. Закрывает, думает "сломан"
5. Не возвращается

**Это killer of distribution thesis.** UGC loop невозможен без onboarding.
