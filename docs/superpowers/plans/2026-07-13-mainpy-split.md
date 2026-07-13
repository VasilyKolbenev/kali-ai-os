# main.py распил — Implementation Plan

> **For agentic workers:** REQUIRED: superpowers:executing-plans (инлайн, eager-коммиты). Checkbox-теги для трекинга.

**Goal:** `kernel/main.py` (2908 строк, 95 роут-декораторов) → доменные `APIRouter`-модули <800 строк каждый; поведение байт-в-байт (страховка: 611 контрактных тестов + правила ниже).

**Architecture:** БОЛЬШИНСТВО эндпоинтов читает `request.app.state` и выносится механически; **~15 замыкают локали `create_app()`** (полный список — ревью 2026-07-13) и требуют управляемых правок по правилам ниже. `create_app()` остаётся в main.py: lifespan + `include_router`. **Роутеры импортируются ВНУТРИ `create_app()`** (не на верхнем уровне main.py) — исключает циклический импорт с shared-хелперами.

**Поправки ревью (обязательные):**
- **(a) Два новых app.state-присвоения** сразу после `app = FastAPI(...)`: `app.state.agents_dir = resolved_agents_dir` (нужен 8 эндпоинтам builder/catalog) и `app.state.db_path = resolved_db_path` (нужен `_get_sandbox`). Значения считаются до lifespan (строки ~292-294).
- **(b) `kernel/routers/_shared.py`** для кросс-модульных хелперов: `_play_audio`, `_mask_key`, `_save_env`, `_get_sandbox(app)`, `_get_skills_catalog(app)`, `_get_skills_registry(app)`. `_build_daily_briefing` — мёртвый код, НЕ трогать.
- **(c) Разрешённые сигнатурные правки** (единственные допустимые изменения тел): добавить `request: Request` эндпоинтам без него (5 шт: /skills/catalog/sources, /skills/catalog, /skills/{name}/export, /skills/{name}/reel, /skills/installed; + /catalog/pack/{name}); `app.` → `request.app.` в /skills/install, /skills/install-bundle; `_speak_response(text)` → `_speak_response(app, text)` (вызов только из /chat); `_get_*`-хелперы получают параметр `app`. OpenAPI не меняется (имена функций/пути сохранены).
- **(d) ВНУТРИмодульный порядок регистрации СВЯЩЕНЕН**: `/skills/{name}/{action}` (сейчас #1632) ДОЛЖЕН регистрироваться раньше `/skills/catalog/refresh` (#2440) — сегодня первый ШЭДОУИТ второй, и это наблюдаемое поведение; `/models/status` определён дважды (первый выигрывает); `/catalog/pack/{name}` и `/catalog/community/install` — раньше `/catalog/{slug}/*`-блока. Порядок def'ов в модуле = порядок в main.py, никакого «наведения красоты».
- **Do-not-move:** `_cors_origins`, `_resolve_host` (импортируются tests/kernel/test_cors.py), CORSMiddleware, lifespan.

**Tech Stack:** FastAPI APIRouter; никаких новых зависимостей; pytest как контракт.

## Карта модулей (kernel/routers/)

| Модуль | Домены (эндпоинтов) | Примерные строки |
|---|---|---|
| `catalog.py` | /catalog/* + /community/* (22) | ~550 |
| `skills.py` | /skills/* включая catalog-sources и reel (13) | ~400 |
| `agents.py` | /agents/* (14) | ~300 |
| `chat.py` | /chat, `_chat_logic`, `_speak_response`, /profile (4) | ~250 |
| `voice.py` | /voice/*, /tts*, /synthesize, /models/* (12) | ~350 |
| `builder.py` | /builder/* (8) | ~200 |
| `life.py` | /budget, /focus, /routines, /notifications, /briefing, /dashboard, /canvas (13) | ~200 |
| `system.py` | /health*, /config, /settings, /llm/test, /sandbox/* (10) | ~250 |
| `ws.py` | websocket-эндпоинты | ~150 |

`main.py` после: импорты + `create_app()` c lifespan + include_router'ы ≈ 700–750 строк (внутри лимита).

## Правила переноса (каждый Task)
1. Создать `kernel/routers/<mod>.py`: `router = APIRouter()`, перенести def'ы БЕЗ изменений тела (только `@app.` → `@router.`), с их локальными константами/хелперами.
2. В `create_app()`: удалить перенесённое, добавить `from kernel.routers import <mod>` + `app.include_router(<mod>.router)` (после lifespan-объявления, порядок include сохраняет порядок регистрации).
3. Гейт после КАЖДОГО модуля: `.venv\Scripts\python.exe -m pytest tests/kernel -q --ignore=tests/kernel/sandbox --ignore=tests/kernel/skill_templates` (полный минус env-DNS) — зелёный = коммит `refactor(kernel): extract <mod> router`.
4. Ничего не «улучшать» по пути (Karpathy surgical); ruff-чистку — только в перенесённых файлах, автофиксы `uvx ruff check --fix kernel/routers/<mod>.py`.
5. Riskiest first: `chat.py` (кросс-хелперы) и `voice.py` (websocket-зависимости) — в начале, пока контекст свежий.

## Tasks
- [ ] T0: `app.state.agents_dir`+`db_path` присвоения + `kernel/routers/__init__.py` + `_shared.py` (6 хелперов, `_get_*` с параметром app) + правка call-sites хелперов в main.py → гейт → commit
- [ ] T1: перенос `chat.py` (/chat, /profile, `_chat_logic`, `_speak_response(app, text)`; `_speak_tasks` set остаётся на app.state — проверить init в lifespan) → гейт → commit
- [ ] T2: `voice.py` (+ найти, кто вызывает `_speak_response`, — импорт из chat) → гейт → commit
- [ ] T3: `skills.py` → гейт → commit
- [ ] T4: `catalog.py` → гейт → commit
- [ ] T5: `agents.py` → гейт → commit
- [ ] T6: `builder.py` → гейт → commit
- [ ] T7: `life.py` + `system.py` → гейт → commit
- [ ] T8: `ws.py` + финальная чистка main.py; проверить размер всех файлов <800 → гейт полный (включая core_loop) → commit
- [ ] T9: ruff по kernel/routers/* (только новые файлы) + финальный прогон + push

**Definition of Done:** все файлы <800 строк · полный kernel-suite + core_loop зелёные · vitest не тронут (эндпоинты те же пути) · diff main.py = только удаления+include.
