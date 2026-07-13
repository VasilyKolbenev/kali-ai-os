# EdgeAI-переход KALI: когда всё заработает без discrete GPU (roadmap v2.0 / v3.0)

> **Прованс:** ultracode-воркфлоу `wf_6f87f3b0-1fc` — 10 research-линз × web-первоисточники → адверсариальная верификация high-impact заявлений → синтез. Внутренний контекст: [KALI 2.0 vision](2026-06-07-kali-2.0-generative-os-vision.md) (лестница A→B→C, три диала), [RESEARCH-2026](../../research/on-device-tts/RESEARCH-2026.md), [PLAN M0–M4](../../research/on-device-tts/PLAN.md), результаты voice-latency Sprint 1 (2026-07-12: NFE16 ✓ / NFE7 ✗ SIM-drop). Языковой констрейнт: **RU + EN co-primary** (Vasily, 2026-07-12). Маппинг версий: **v2.0 = ступени A→B с locality-диалом в on-device; v3.0 = ступень C (полностью генеративная + девайс)**.

**Дата анализа:** 2026-07-12. Все числа — из проверенных первоисточников (verdict CONFIRMED, если не помечено иначе). Ключевой вывод всего исследования: **гейтит не NPU TOPS, а memory bandwidth (77–85 GB/s у всех флагманов 2025) + термальный бюджет + лицензии на TTS-веса.** Ноутбук-без-dGPU — почти решён уже сегодня; телефон-флагман — 2027 (LPDDR6); midrange — 2028+ (DRAM-кризис, +78–89% QoQ на LPDDR5X).

---

## 1. Оценка готовности EdgeAI-перехода

Статус «сегодня» (июль 2026). 🟢 = работает на целевом качестве, 🟡 = работает с оговорками / требует нашей работы, 🔴 = заблокировано (железом, качеством или лицензией).

| Компонент | RU | EN | Телефон | Ноутбук без dGPU |
|---|---|---|---|---|
| **STT** | 🟢 GigaAM v2/v3 (MIT, ~4.6% WER, 225 MB в браузере); parakeet-tdt-0.6b-v3 RU WER 5.51%, CC-BY-4.0 | 🟢 parakeet EN 4.85% WER; whisper.cpp / WhisperKit real-time | 🟢 флагман (ANE ~190x RT, WhisperKit 0.45s latency; энергия 0.3 W); 🟡 midrange (CPU-int8, 100–250M модели) | 🟢 Whisper INT4 быстрее real-time на CPU; официальный Ryzen-AI-NPU путь. Только runtime swap, архитектура не меняется |
| **LLM-router** (диалог/оркестрация, 7–9B) | 🟡 YandexGPT-5-Lite-8B GGUF / QVikhr-3 (+13–21% к базе на RU); tokenizer tax: 3.1–3.9 tok/слово generic vs 2.3–2.4 Cyrillic-dense (~24% throughput) | 🟡 8B Q4 = 12–24 tok/s на Copilot+ / M4 — разговорный темп; 14B Q4 маргинально (~10–14 tok/s) до LPDDR6 | 🔴 8B = 5–12 tok/s burst, шина 85 GB/s насыщается; 🟡 3–4B = 10–32 tok/s (потому Apple/Google возят ~3B). Sustained −41.5% за минуты (термо) | 🟢 iGPU/CPU (НЕ NPU — NPU это prefill/ASR-акселератор: Lunar Lake NPU = 60–70% своего же iGPU) |
| **LLM-builder** (SKILL.md по голосу, multi-turn) | 🔴 RU-бенчмарк tool-calling НЕ СУЩЕСТВУЕТ — порог надо мерить самим (frozen RU eval set по образцу TTS-gate) | 🟡 4B-класс: 97.5% tool-calls (Qwen3.5-4B, 40-кейсовый eval — одна точка данных), TAU2 79.9%, IFEval 90%+; но multi-turn: лучшие sub-10B ~50% BFCL v4 vs ~75–77% frontier | 🔴 multi-turn agentic gap + термо + context 4k у платформенных моделей | 🟡 viable как constrained-decoding + validate-repair loop (grammar-поля гарантированы, семантика ловится валидаторами), НЕ как freeform-генерация |
| **TTS** | 🔴 **двойной блок**: F5-RU веса CC-BY-NC (NC переживает finetune И дистилляцию — подтверждено maintainer'ом); Silero тоже NC. F5 на CPU RTF ~3 (⚠️ единичная неатрибутированная точка — перемерить in-house) | 🟡 Kokoro-82M Apache-2.0, real-time CPU, но БЕЗ RU и БЕЗ cloning | 🔴 DiT/flow-matching не real-time ни на одном телефоне; Kokoro RTF 0.6–0.8 на флагманах; cloning+RU+phone = 12–18 мес (distilled CosyVoice3-класс на NPU) | 🟡 Supertonic-3 (99M, 31 язык вкл. RU, RTF 0.31 на 4-ядерном CPU, OpenRAIL-M — нужен legal review; cloning закрыт за Voice Builder) |
| **UI-gen** (generative shell) | 🟡 паттерн языко-независим, но RU-качество малых моделей не мерялось | 🟢 cloud: A2UI v0.8 / MCP Apps (SEP-1865) / json-render — 91.3% first-attempt, 99.2% после retry; предпочтение до 72% vs чат | 🔴 механика доказана на 3B (Apple guided generation), но качество композиции ниже 30B не продемонстрировано никем | 🟡 Qwen3-30B-A3B (MoE, ~3B active) — минимальная модель с измеренным production-качеством; сильный ноутбук ~2027 |
| **Hardware floor** | — | — | 🟡 флагман 12GB (iPhone 17 Pro) — burst-режим OK; 🔴 sustained (термо-стена 40s–4.2 мин; S24 Ultra вообще убивает inference); 🔴 midrange — откат к 6–8GB из-за DRAM-кризиса | 🟢 Copilot+ floor: 40+ TOPS, 16GB, ~120–135 GB/s, цена от **$550** — installed base уже формируется |

**Честный итог:** полный voice-loop (STT + 4–8B LLM + TTS) на ноутбуке за $550–800 работает УЖЕ СЕГОДНЯ — если TTS заменить/дистиллировать. Единственный hard blocker всего перехода — TTS: и по latency (RTF), и по лицензии (own-weights = on-device + license-clean одним ходом, как и записано в RESEARCH-2026.md).

---

## 2. Роадмап v2.0 (on-device ступени A→B)

### Фаза A-0 «Фундамент» — БЕЗ триггера, делать сейчас
Это работа, без которой ни один следующий триггер нельзя ни поймать, ни отработать.

**Что строить сейчас (мэппинг на существующие артефакты):**
- **Лицензионно-чистая TTS-база** — решение №1. Текущий F5-RU finetune (Misha24-10) юридически неотгружаем в платный продукт ($9.99/mo). Варианты: (a) дождаться commercial F5-base (SWivid/F5-TTS discussion #997), (b) CosyVoice3-0.5B (Apache-2.0, RU+EN, zero-shot cloning) как teacher, (c) Supertonic-3 после OpenRAIL-M review. Встраивается в M1–M2 плана `research/on-device-tts/PLAN.md`.
- **Hero voice: записать 10–15 ч студии RU** (+2–3 ч EN для акцента) — данные, не GPU, критический путь; compute на finetune-итерацию <$100 (RTX 4090 $0.20–0.34/hr, H100 $1.5–3.3/hr).
- **EN quality-gate set** для `scripts/tts_quality_gate.py` (сейчас RU-only, а RU+EN co-primary).
- **Frozen RU tool-call eval set** (аналог TTS-gate): RU-бенчмарка structured-output в природе нет — без своего сета триггеры фаз A-2/B невозможно измерить.
- **Замерить F5 CPU RTF in-house** на Copilot+-классе железа (цифра «RTF ~3» не атрибутирована) — это baseline M0, прогоны уже есть.
- **Архитектура builder'а**: перевести генерацию SKILL.md на constrained decoding (llama.cpp GBNF на YAML/структурные поля) + validate-repair loop уже на cloud-модели — это решение доступно сейчас и оно же делает будущий переход на 4–9B возможным (grammar гарантирует валидность на любом размере; внимание: coverage грамматик на сложных схемах падает — держать схемы простыми).

### Фаза A-1 «Ноутбук без dGPU» — цель: конец 2026
- **Триггер (свой, измеримый):** дистиллированный TTS проходит CER+SIM gate (PASS по `tts_quality_gate.py`) при **RTF < 0.5 на Copilot+ CPU/NPU**. Мониторить: собственный harness + релизы DMOSpeech2 (студент 4-step УЖЕ бьёт F5-учителя: WER 1.752 vs 1.947, SIM 0.698 vs 0.662, MIT-код) и IntMeanFlow (3-NFE для F5 text2mel; веса пока не выложены).
- **Второй триггер:** NFE7-провал (SIM −0.026) подтвердил: нужна SV-loss дистилляция, не срезание шагов — DMOSpeech2-рецепт (DMD2 + RL duration) это ровно оно.
- **Что делает KALI в фазе:** Windows-tier без RTX: GGUF 4–8B (YandexGPT-5-Lite / Qwen3.5) на iGPU через llama.cpp Vulkan + whisper INT4 + distilled TTS. Существующий ollama-tier в LLM Router — готовая точка подключения. NPU — только prefill/Whisper offload, НЕ decode.
- **Эффект:** требование «RTX GPU» исчезает из системных требований → TAM растёт на весь парк Copilot+ ($550+).

### Фаза A-2 «Телефон-флагман standalone» — цель: H2 2027
- **Триггеры (все три, где мониторить):**
  1. LPDDR6-телефоны в продаже (>120 GB/s): анонс Snapdragon 8 Elite Gen 6 Pro на Snapdragon Summit **сентябрь–октябрь 2026**, телефоны H1-2027 (androidauthority, wccftech leaks — сам факт проверять по анонсам Qualcomm).
  2. Независимые sustained-замеры: **8B-q4 ≥15 tok/s 10+ минут без OS-kill** (методология arXiv 2603.23640; notebookcheck-класс обзоры).
  3. Свой RU tool-call gate ≥95% на модели ≤8B GGUF (проверять на каждом релизе Qwen/Vikhr/T-lite — Vikhr исторически догоняет новую базу за месяцы).
- **Что делает KALI:** флагманский standalone-tier: 4B RU-tuned (сегодня это QVikhr-3-4B) для intent/routing + cloud для тяжёлого reasoning; distilled TTS на NPU; duty-cycle архитектура wake-word (mW) → streaming STT (0.1–0.3 W) → LLM burst (2–6 W, ≤20 s/turn) → sleep. **Никаких resident agent-loops** — термо-стена это физика, не software.
- **Что строить до триггера:** (a) **бесплатный platform-tier в LLM Router уже сейчас**: Apple Foundation Models (3B on-device, **RU в списке локалей**, tool calling, guided generation, $0) для будущего iOS-билда; Gemini Nano Prompt API (ML Kit) в Android `LlmClient` рядом с anthropic/openai BYO-key — с оговорками: foreground-only, квоты (ErrorCode.BUSY), prompt <1024 tok, **RU-качество не документировано — проверить эмпирически** (SKILL.md=system-prompt в standalone как раз влезает после trim); (b) абстракция «platform voice provider» (SpeechAnalyzer iOS / ML Kit Speech Android) с F5/ElevenLabs как quality-путь.

### Фаза B «Generative shell» — параллельно, cloud-first сейчас
- **Триггер для on-device:** малые модели (3–9B) пересекают ~90% first-attempt validity на A2UI-композиции с приемлемым качеством. Мониторить: JSONSchemaBench/StructEval-линейку на arXiv, появление small-model reference-finetunes у A2UI (a2ui.org/ecosystem), BFCL v4 sub-10B.
- **Что делает KALI:** shell на **declarative JSON + trusted component catalog** (паттерн A2UI/json-render), НЕ LLM-генерируемый HTML. Cloud-LLM генерирует, клиент рендерит нативно; validation+retry даёт 99%+ renderability уже сегодня (Google возит это в Gemini Enterprise).
- **Что строить сейчас:** каталог компонентов — A2UI-совместимый формат (**первопартийный Flutter-рендерер бесплатно** — прямо в mobile-стек KALI) + json-render-паттерн (Zod-каталог) для React-десктопа. Генератор — swappable через существующий LLM Router: cloud сегодня, локальный 3–8B finetune по триггеру. **Каталог — и есть архитектурное решение, делающее small-model переход возможным**: задача сжимается из «генерируй UI» в «выбери/заполни компоненты».

---

## 3. Роадмап v3.0 (ступень C — полностью генеративная + девайс)

Честно: почти всё здесь — research-stage. Ставить дедлайны нельзя, ставить триггеры — можно.

### C-1 «Полностью генеративный интерфейс» (без каталога)
- **Статус:** research. Free-form генерация UI = паритет с экспертами только в ~50% случаев (arXiv 2604.09577), latency не решена; on-device качество композиции ниже 30B никем не показано.
- **Триггеры:** (a) BFCL v4 sub-10B ≥70% (сейчас ~50%: LFM2.5-8B-A1B 49.7% — gorilla.cs.berkeley.edu/leaderboard.html); (b) Densing Law (плотность способностей ×2 каждые ~3.3 мес, Nature MI 2025) доводит frontier-2026 multi-turn agentics до 4–9B — расчётно **H2 2027**, проверять по факту релизов; (c) платформенные on-device модели с context >8–16k (WWDC27 / ML Kit release notes).
- **Что делает KALI:** каталог из фазы B становится «нижним слоем» — free-form генерация допускается поверх проверенных компонентов. Ничего строить заранее не нужно, кроме того, что уже строится в B.

### C-2 «Генеративная OS»
- **Статус:** research + platform-dependent. Шаблон уже виден: Apple AFM 3 Core Advanced = **20B sparse (1–4B active) на iPhone 17 Pro** — доказательство, что assistant-grade качество приходит на телефон через sparsity+QAT, а не через RAM.
- **Триггеры:** (a) 10–20B-sparse-класс + стабильный function calling в AICore/CoreML для third-party; (b) 16GB RAM в стандартном (не-Pro) флагмане; (c) фоновая inference-политика Android ослаблена (сейчас top-foreground-only — hard blocker для proactive-агентов с LLM в цикле).
- **Что делает KALI:** «три диала» из `docs/architecture/2026-06-07-kali-2.0-generative-os-vision.md` уже спроектированы под это — reasoner locality постепенно сдвигается на девайс по компонентам (STT уже → TTS после дистилляции → builder-LLM → conversational LLM последним), а не единым cutover. Latency-экономика сама подталкивает: cloud RTT 200–500 ms до first token vs <20 ms/token локально.

### C-3 «Custom device»
- **Статус:** до 2028 не считать. Экономика против: DRAM-кризис (память = 30–40% BOM vs исторические 10–15%), midrange откатывается к 6–8GB, 12GB-midrange-norm сдвинулся к **~2028 (projection, не факт)**.
- **Единственный обнадёживающий контрпример:** dedicated edge NPU (Hailo-10H): 6.9 tok/s **бесконечно** при 1.87 W без троттлинга — детерминированный термо-профиль кастомного девайса решает проблему, которую телефоны решить не могут. Это аргумент ЗА девайс в ladder, но после того, как софт-стек доказан на чужом железе.
- **Что строить сейчас:** ничего. Записать триггер: BOM-калькуляция становится осмысленной, когда LPDDR6 + 3–4B RU-модель + distilled TTS вместе укладываются в <$150 BOM.

---

## 4. Dashboard мониторинга

| # | Сигнал | Измеримый порог | Где смотреть | Частота | Действие при срабатывании |
|---|---|---|---|---|---|
| 1 | Собственный TTS-gate (дистилляция) | PASS CER+SIM при RTF<0.5 на Copilot+ CPU/NPU | `scripts/tts_quality_gate.py` + M0-бейзлайны в `research/on-device-tts/` | каждый distill-run | Ship ноутбук-без-RTX tier (фаза A-1) |
| 2 | Commercial F5-base / IntMeanFlow weights | Лицензионно-чистый F5-класс checkpoint ИЛИ 1–3-NFE веса выложены | github.com/SWivid/F5-TTS/discussions/997; arXiv 2510.07979 / github IntMeanFlow | ежемесячно | Перезапустить distill-pipeline на чистой базе; hero-voice finetune (<$100/итерация) |
| 3 | RU+EN TTS с cloning на CPU | Kokoro+RU, NeuTTS+RU, или Supertonic открывает cloning | huggingface.co/hexgrad; github.com/neuphonic/neutts; github.com/supertone-inc/supertonic | ежеквартально | Оценить как замену own-distill пути (дешевле) |
| 4 | LPDDR6 в телефонах | Анонс SoC с LPDDR6 (>120 GB/s) | Snapdragon Summit **сен–окт 2026** (qualcomm.com, androidauthority) | по событию + квартально | Старт порта phone-local LLM tier (фаза A-2) |
| 5 | Sustained decode на флагманах | 8B-q4 ≥15 tok/s 10+ мин без OS-kill | независимые обзоры (методология arXiv 2603.23640), notebookcheck | ежеквартально | Флагманский standalone из «companion» → «primary» |
| 6 | BFCL v4 sub-10B | ≥70% (сейчас ~50%) | gorilla.cs.berkeley.edu/leaderboard.html | ежеквартально | Voice-builder multi-turn на локальной модели |
| 7 | TAU2/tool-calling в 4B model cards | TAU2 ≥75 у нового 4B (Qwen3.5-4B уже 79.9) | HF model cards: Qwen / Nemotron Nano / LFM / xLAM | по релизам | Прогнать через свой RU tool-call gate (п.8) |
| 8 | Собственный RU tool-call gate | ≥95% на ≤8B GGUF (бенчмарка в природе нет — только свой) | собственный frozen eval set (построить в A-0!) | по релизам моделей | Флип agent-execution на local tier |
| 9 | RU small-model качество | RU-tuned 4–9B на уровне топа; скорость Vikhr-turnaround после новой базы | mera.a-ai.ru (фильтр <10B), llmarena.ru, huggingface.co/Vikhrmodels; НЕ github ru_llm_arena (мёртв с окт-2024) | ежеквартально | Обновить local-tier checkpoint (Cyrillic-dense tokenizer приоритетен: −24% токенов) |
| 10 | Открытие Alice-Lite / T-lite 3.0 | Yandex открывает пред-поколение (паттерн: YGPT-5-Lite фев-2025); T-Bank шипит 7–9B на Qwen3.x | habr.com/ru/companies/yandex, /tbank; HF yandex, t-tech | ежеквартально | Лучший RU on-device checkpoint дня — немедленный eval |
| 11 | LiteRT NPU coverage | Делегаты на Snapdragon 7-series / mid-Dimensity (сейчас только 8-series) | developers.google.com/edge/litert/next/qualcomm | ежеквартально | Mass-market Android NPU tier становится реальным |
| 12 | Apple platform-стек | AFM context >8k GA; TTS API third-party; SpeechAnalyzer RU locale | WWDC (июнь) + iOS .4-релизы; machinelearning.apple.com | WWDC + point-релизы | iOS-tier: сбросить свой LLM/STT payload, оставить только TTS |
| 13 | Gemini Nano для KALI | (a) RU inference подтверждён эмпирически; (b) function calling в Prompt API; (c) background policy ослаблена | developers.google.com/ml-kit/genai + собственный тест на Pixel/S25 | ежеквартально | Включить GeminiNano-provider в mobile `LlmClient` (cost 0) |
| 14 | RAM/DRAM-кризис | 12GB стандарт в $300–400 midrange; контрактные цены LPDDR5X развернулись | TrendForce (trendforce.com), techradar | раз в полгода | Пересчитать сроки C-фаз и midrange-TAM (recheck H2 2027) |
| 15 | Platform-builder угроза | AI Studio Mobile-паттерн «speak → software» идёт от developers к consumers; условия Copilot SDK на GA | Google I/O (май), MS Build (май), WWDC (июнь), SDC (окт) | ежеквартально | Ускорить UGC-loop; оценить Copilot SDK как distribution surface |

---

## 5. Упаковка и сегментация (RU/EN) — вопрос Vasily 2026-07-12

Три стратегии доставки двуязычных on-device моделей (размеры — из research-данных этого воркфлоу):

**Размеры языковых паков (ориентиры):**
- **RU-пак:** F5-RU 336M fp16 ~0.7 GB (или будущий distilled student ~0.2–0.4 GB) + vocos + ruaccent (~150 MB) + GigaAM/whisper-small ~0.5 GB + [фаза A-2] RU-LLM 4B-q4 ~2.5 GB → **~1.4 GB голос-only / ~4 GB со standalone-LLM**
- **EN-пак:** заметно меньше — Kokoro-82M (Apache-2.0) ~0.3 GB + whisper ~0.5 GB + [A-2] Qwen-класс 4B-q4 ~2.5 GB → **~0.8 GB голос-only**. Асимметрия размеров = ещё один аргумент EN-first.
- Текущий premium-бандл: 4.9 GB (RU-only, RTX-tier).

| | (a) Раздельные инсталяторы | (b) Один инсталятор + докачка языкового пака | (c) Гибрид |
|---|---|---|---|
| Суть | RU-билд и EN-билд с зашитыми моделями | Лёгкий универсальный (~1–2 GB) + пак выбранного языка при онбординге | (b) по умолчанию + полный оффлайн-бандл «всё включено» для сегментной раздачи |
| Инфраструктура | ×2 CI/QA-матрицы, ×2 листинга | **УЖЕ ЕСТЬ**: onboarding-шаг `models-download` + `model_downloader` — расширить до per-language паков | (b) + InnoSetup DiskSpanning уже умеет большие бандлы |
| Смена языка | переустановка ✗ | докачка пака ✓ | докачка ✓ |
| Кросс-языковой UGC (RU-агент прилетел EN-другу) | сломан или деградация в cloud-TTS | **решается**: «агент говорит по-русски — докачать голос (1.4 GB)?» — тот же механизм | как (b) |
| EN-first on-device rollout | чистый, но дорогой в поддержке | естественный: EN-пак просто готов раньше в том же билде | как (b) |
| Минусы | стоимость ×2, UGC-кросс, дрейф версий | первый запуск требует сети + CDN-трафик (уже гейт A3 в launch-плане) | сложность матрицы билдов |

**Рекомендация: (b) как дефолт, (c) для дистрибуции.** Инфраструктура докачки уже в проде (модели и так тянутся после установки), один листинг в сторах, кросс-языковой UGC не ломается, EN-first-раскатка сводится к «какой пак готов». Раздельные инсталяторы (a) оправданы только если магазины/маркетинг потребуют отдельные локализованные листинги — тогда это (c) с per-locale бандлами из той же матрицы паков. Решение затрагивает Lane A launch-плана (CDN c range-докачкой — уже требование A3).

---

## 6. Риски и контр-ходы

### 6.1 Platform-holder: угроза И рычаг одновременно
**Угроза:** к концу 2026 «говорящий ассистент» коммодитизируется полностью — Gemini-Siri в iOS 27 (сент-2026), Copilot в taskbar + 100+ prebuilt-агентов, Gemini на каждом Android. Persona-слой («Jarvis») перестаёт дифференцировать. Google AI Studio Mobile («скажи идею — приложение соберётся») — самый близкий шаг к тезису KALI; окно до движения downmarket ≈ **12–24 мес**.
**Рычаг:** те же платформы дают бесплатную инфраструктуру: AFM (3B, **RU поддержан**, tool calling, $0/token), Gemini Nano, SpeechAnalyzer (2.2x быстрее Whisper large-v3-turbo). Ни один platform-holder не возит: (1) voice-first СОЗДАНИЕ агентов для non-tech, (2) портируемость агентов между экосистемами (SKILL.md-ставка усиливается), (3) RU-рынок (Apple Intelligence/Galaxy AI/Copilot в РФ не обслуживаются — вакуум durable).
**Контр-ход:** platform-модели — только optional accelerators в Router, никогда единственный путь (квоты AICore, LAF-токены Microsoft, гео-гейтинг à la «Phi Silica не в Китае» = kill-switch risk). Moat = creation + share loop + RU-native voice, и его надо добежать ДО того, как «speak an idea» дойдёт до консьюмеров.

### 6.2 RU-vs-EN асимметрия → опция EN-first on-device rollout
EN-триггеры срабатывают раньше RU: EN TTS с permissive-лицензией уже есть (Kokoro Apache-2.0, CPU real-time), EN tool-calling бенчмарки публичны (BFCL/TAU2), NeuTTS доказал cloning на бюджетном телефоне — но EN-only. RU везде отстаёт на один ход: tokenizer tax ~24%+, ни одного RU structured-output бенчмарка, RU TTS «чистый» только Supertonic-3 (OpenRAIL-M, cloning закрыт) или свой distill.
**Контр-ход:** держать **EN-first on-device rollout** как явную опцию — ноутбучный no-dGPU tier можно запустить EN-only на квартал-два раньше (Kokoro + Qwen3.5 + whisper), RU догоняет по готовности own-voice distill. Это и рыночно осмысленно (public launch за пределами РФ) — но решение продуктовое, за Vasily. Обязательный шаг в любом случае: EN-set для TTS-gate (сейчас его нет).

### 6.3 Лицензии — самый недооценённый блокер
- **F5-RU веса CC-BY-NC: NC переживает и finetune, и дистилляцию** (подтверждено maintainer'ом). Текущий prod-голос юридически неотгружаем в $9.99/mo продукт. Silero — тоже NC. Контр-ход: own-weights стратегия (уже в RESEARCH-2026.md) = hero voice 10–15 ч студии + чистая база (CosyVoice3 Apache-2.0 / commercial-F5-base когда появится / Chatterbox MIT как teacher); compute тривиален (<$100/итерация, вся кампания — низкие тысячи $).
- **Frontier ToS против дистилляции** — enforcement активен (OpenAI-DeepSeek, ~24k фрод-аккаунтов у Anthropic). Синтетику для builder-LLM (5–15k пар «голосовой запрос → SKILL.md») генерировать ТОЛЬКО из MIT/Apache моделей (DeepSeek-R1 явно разрешает дистилляцию; Qwen Apache-2.0). LoRA 7–8B на 5–15k примерах = в 1–3 пунктах от GPT-4o на узкой структурной задаче за $5–500/run.
- **OpenRAIL-M (Supertonic-3)** — commercial permitted с behavioral restrictions: перед любым ship — legal review.

### 6.4 Solo-founder focus risk
Этот роадмап — 15 сигналов и 4 фазы; попытка гнаться за всеми = смерть по расфокусу (anti-pivot rule binding). Контр-ходы:
- **Дашборд — квартальный ритуал** (1 сессия/квартал + событийные точки: Snapdragon Summit сен–окт-2026, WWDC, I/O, Build), не фоновый мониторинг.
- **Единственный critical-path артефакт до конца 2026 — TTS**: hero voice + чистая база + distill до PASS-gate. Всё остальное (platform-tiers, каталог shell, RU eval set) — bounded-задачи на 1–3 дня, встраиваемые между продуктовыми спринтами.
- **Правило одного триггера:** новая фаза открывается только по измеримому порогу из дашборда, не по хайповому анонсу. Peak-TOPS и vendor-маркетинг игнорируются by design — считаются только sustained-замеры и собственные gates.
- Продукт живёт на cloud+RTX уже сейчас и приносит пользователей независимо от перехода: EdgeAI — про снятие hardware-барьера дистрибуции, не про выживание. Переход делается по-компонентно (STT → TTS → builder → conversational), каждый компонент — как только влезает; единого «дня X» нет.

### 6.5 Технические риски второго порядка
- **Термальная стена — физика:** sustained LLM на телефоне = троттлинг −41.5% за минуты / OS-kill (S24 Ultra); всегда-on агентские циклы на телефон не переносятся вообще — duty-cycle архитектура закладывается сейчас, в дизайн mobile-runtime (напоминалки без LLM в цикле — уже правильное решение).
- **Runtime-фрагментация:** specialist-модель, бьющая бенчмарк (xLAM-2-8b: 69.25% BFCL), упала до 15% из-за chat-template mismatch в LM Studio — каждый checkpoint прогонять через собственный gate в ЦЕЛЕВОМ runtime, не верить leaderboard-цифре.
- **Неверифицированные цифры, на которых нельзя гейтить решения:** F5 CPU «RTF ~3» (неатрибутированная единичная точка — перемерить), Gemini Nano ~940 tok/s (unofficial), «12GB-midrange к 2028» (projection), RU-качество Gemini Nano (не документировано).