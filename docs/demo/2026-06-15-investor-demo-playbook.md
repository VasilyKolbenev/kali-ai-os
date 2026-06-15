# KALI — Investor Demo Playbook (2026-06-15)

**Format:** live, on Vasily's PC (RTX + local mic). In-person.
**Goal:** finished-product impression of the hero flows + a clear vision arc.
**Principle:** demo only the paths verified green below. Everything else stays
off-stage.

---

## Readiness traffic-light (verified live on the fresh build)

| Flow | Status | Evidence |
|---|---|---|
| Jarvis speaks (TTS) | 🟢 | `/tts/speak` plays, 4.9 s phrase; accent checkpoint, «готОв» correct |
| STT recognizes Russian | 🟢 | reference speech transcribed correctly in 0.7 s |
| Record window holds a pause | 🟢 | end-of-utterance silence raised 1 s → 2.5 s |
| Agent enable actually works | 🟢 | currency returns real rates (was 403); permission granted on «Включить» |
| Weather by Russian city | 🟢 | «Москва» → 21.4° (was "city not found"); Latin still works |
| One bad call ≠ broken agent | 🟢 | bad city leaves agent «running»; next call succeeds |
| Honest store statuses | 🟢 | `/agents/config-status`: key-needing agents show «Нужна настройка» |
| Jarvis doesn't fake actions | 🟢 | "сделай агента" → "это в «Создать голосом», сэр" |
| Create skill by voice → deploys | 🟢 | builder start→answer→deploy writes a real skill to disk |
| Voice-created skill shows in «Мои» | 🟡 | verify on the fresh install (Rust :3006 route) before relying on it on stage |
| App stability (restarts, tabs) | 🟡 | re-confirm on the fresh install (lock + black-screen fixes shipped) |
| Real-mic accuracy ("hears ME") | 🟡 | only Vasily can confirm — do the 5-phrase mic pass below |

🟡 = must be re-confirmed on the fresh install before the meeting (steps below).

---

## The demo script (≈6–8 min, ordered for reliability)

> Rule: **type or speak only the phrases below** — they're on verified paths.
> Let the first synth warm up BEFORE the investor is watching (say one phrase
> to Jarvis ~1 min before; the first synthesis is the slowest).

**1. Cold open — talk to Jarvis (voice, 60 s)**
- "Привет, Джарвис. Какая погода в Москве?" → spoken answer with correct stress.
- "А курс доллара?" → spoken rate.
- Beat: *"Это локально, на моём железе. Ничего не уходит в облако."*

**2. The wedge — create an assistant by voice (90 s)**
- Open «Создать голосом».
- "Напоминай мне пить воду каждые два часа." → wizard asks 1–2 questions →
  preview → confirm.
- Beat: *"Обычный человек только что создал себе агента голосом. Без кода."*

**3. Personalization — memory (45 s)**
- "Запомни: меня зовут Василий, у меня кот Барсик."
- (optional, strongest if you restart once earlier) ask later "как зовут моего
  кота?" → "Барсик, сэр."
- Beat: *"Он запоминает меня. Локально. Это и есть доверие."*

**4. The store — Мастерская (45 s)**
- Open «Мастерская» → Витрина: life categories, RU cards.
- Enable «Погода»/«Курсы валют» in one click → «Работает».
- Show a key-needing one (Telegram) → «Нужна настройка» → the inline key dialog.
- Beat: *"Магазин готовых помощников для непрограммиста. Честные статусы — что
  работает, что просит ключ."*
- «Сообщество» tab → the interop pitch line.

**5. The vision — close (90 s)**
- One sentence each: generative-OS North-Star · the moat (trust/local + the
  non-tech voice wedge + UGC) · the model is a swappable commodity.
- Reference: `docs/architecture/2026-06-07-kali-2.0-generative-os-vision.md`.

---

## Do NOT show on stage (off the verified path)

- **News agent** — needs a NewsAPI key; shows «Нужна настройка». Don't click
  «Включить» expecting headlines.
- **Email / Notion / Todoist / smart-home** — need real credentials/OAuth.
  Fine to *mention* the «Нужна настройка» flow; don't try to make them work live.
- **Random off-script voice commands** — STT is good but not perfect; stick to
  rehearsed phrases. If a command isn't understood, just repeat it.
- **First synthesis cold** — warm it up before the investor watches.
- **Showcase / Activity / advanced catalog** — dev surfaces; not in the 4-icon
  nav anyway.

---

## Investor Q&A — honest answers ready

- **"Работает офлайн?"** — Да, голос и память локальные. Сейчас при первой
  установке модели догружаются один раз из сети; бандл моделей для полностью
  офлайн-первого-запуска — ближайший пункт роадмапа.
- **"Чей это голос / лицензия модели?"** — Русский F5-файнтюн, лицензия
  CC-BY-NC (некоммерческая). К коммерческому запуску — договор с автором,
  своя модель или замена; слой модели у нас намеренно сменный.
- **"Чем отличаетесь от OpenAI/Claude/умных колонок?"** — Голосовое СОЗДАНИЕ
  агентов для непрограммиста + локальные данные/доверие + UGC-дистрибуция.
  Гиганты делают агентов для разработчиков в облаке; мы — для строителя/врача,
  на его железе.
- **"Монетизация?"** — (твоя стратегия — впиши свой ответ; варианты в роадмапе:
  Premium-устройство, маркетплейс, BYO-ключ vs подписка).
- **"Сколько готово / что MVP?"** — Голос, создание агентов, магазин, память —
  работают. Широта интеграций и офлайн-бандл — в работе; архитектура (Rust-ядро,
  generative-OS) заложена под масштаб.
- **"Кто конкуренты?"** — AI New World (прямой), Hermes/OpenJarvis/OpenHuman
  (соседние, tech-аудитория). Наш ров — непрог-голос + локальность + UGC.

---

## Pre-meeting checklist (run the morning of)

1. Reinstall the fresh build; launch → splash «Джарвис запускается…», NOT the
   wizard. Sidebar = 4 icons.
2. Warm voice: one phrase to Jarvis. Confirm audible + «готОв» correct.
3. Mic pass — say these 5, note hit-rate (target ≥4/5):
   - "Какая погода в Москве?"
   - "Какой курс доллара?"
   - "Напоминай пить воду каждые два часа."
   - "Запомни, меня зовут Василий."
   - "Сколько у меня задач?"
4. Restart the app 2–3× — comes up each time, no red dot.
5. Open each of the 4 nav icons + Мастерская segments — no black screen.
6. Create one skill by voice end-to-end; confirm it appears in «Мои».
   *(If it doesn't appear without a restart — report back, that's a fix.)*
