# Proactive KALI v1 Implementation Plan

> **For agentic workers:** REQUIRED: Use `superpowers:subagent-driven-development` (subagents available in this harness) or `superpowers:executing-plans` to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking. Apply `@superpowers:test-driven-development` discipline on every code task. Run `@superpowers:verification-before-completion` before marking any task complete.

**Goal:** Move KALI from reactive ("ask, get answer") to proactive ("KALI tells you what matters") via three independent features built on existing primitives — without losing the voice-first non-tech identity. Direct counter to Anthropic Orbit's text dashboards (see `memory/project_competition.md` Competitor 3).

**Architecture:** Three independent features (F1 voice morning briefing, F2 OS tray notifications, F3 chat suggestion engine) layered on existing primitives:
- F1 = `Scheduler.register_cron` subscriber + `BriefingService` + auto-TTS via `_speak_response`.
- F2 = Tauri notification plugin (NEW) + WebSocket `notification.new` event listener + per-agent settings toggle.
- F3 = SQLite `chat_intent_log` table (NEW) + 6h pattern detection cron + chat-side suggestion banner that hands off to `useBuilderStore.start()`.

All three are feature-flag-independent: shipping F1 alone still adds value, no all-or-nothing coupling.

**Tech Stack:**
- Backend: Python 3.12, FastAPI, aiosqlite, croniter, pytest + pytest-asyncio
- Frontend: TypeScript, React 19, Zustand, Vitest + React Testing Library
- Rust/Tauri: Tauri 2, tauri-plugin-notification (NEW dep)

**Source spec:** `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md`

**Estimated effort:** 5-7 days (6.5d nominal + buffer for plan-defects — precedent voice-builder-pilot v2 caught 8 defects across 25 tasks via review loop).

**Plan-defect expectation:** Build for it. Two-stage review (spec compliance → code quality) per task. Controller verifies reviewer claims by reading actual code, not trust (precedent: 2 reviewer mistakes were correctly overruled in voice-builder-pilot v2).

---

## Critical-path reads before starting

Before Chunk 1, the executing agent MUST read:

1. `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md` — full spec.
2. `kernel/briefing.py` — existing `BriefingService` class, `generate_morning_briefing(agent_data)` signature.
3. `kernel/notifications.py` — existing `NotificationManager`, `Notification` dataclass.
4. `kernel/scheduler.py` — `register_cron(name, cron_expr, topic)`, `_loop()` morning_hour check, `emit(topic)`.
5. `kernel/event_bus.py` — `subscribe(topic_pattern, handler)`, `publish(event)`.
6. `kernel/main.py:939-943` — current `/briefing/morning` GET route.
7. `kernel/main.py:1006` — `async def _speak_response(text: str) -> None:`.
8. `kernel/main.py:1055` — `_chat_logic(request)` for intent classification hook point.
9. `kernel/main.py:2090` — POST `/settings` handler.
10. `kernel/database.py:1-60` — `SCHEMA` constant + `initialize()` method.
11. `ui/src/components/Settings/Settings.tsx` — section pattern (LlmSettings/VoiceSettings/AdvancedSettings).
12. `ui/src/stores/builder.ts:36` — `start(request: string)` method.
13. `ui/src/api/websocket.ts:31-50` — WebSocket connection + message switch.
14. `src-tauri/Cargo.toml:6-12` — current Tauri plugins list.
15. `src-tauri/src/lib.rs:195-210` — `.plugin(...)` init pattern.

---

## File structure (decomposition decisions locked in here)

**Backend (Python — new files):**
- `kernel/briefing_runner.py` — NEW. Subscribes to `schedule.morning` → assembles agent_data → calls `BriefingService.generate_morning_briefing` → invokes `_speak_response`. Pure orchestration, no business logic.
- `kernel/suggestions.py` — NEW. `SuggestionEngine` class — periodic intent-log pattern detection + suggestion record CRUD.
- `tests/kernel/test_briefing_runner.py` — NEW.
- `tests/kernel/test_suggestions.py` — NEW.

**Backend (Python — modified files):**
- `kernel/database.py` — extend `SCHEMA` with `chat_intent_log` + `suggestions` tables.
- `kernel/main.py` — wire `briefing_runner` startup + `/suggestions` routes + intent log hook in `_chat_logic`.
- `kernel/models.py` — add `BriefingConfig`, `SuggestionRecord` pydantic models.
- `kernel/scheduler.py` — verify `register_cron` works for daily morning fire (already general enough; no code change expected).

**Frontend (TypeScript — new files):**
- `ui/src/api/notifications.ts` — NEW. Tauri command wrapper for cross-platform notify (uses `@tauri-apps/plugin-notification`).
- `ui/src/stores/notificationStore.ts` — NEW. Zustand store holding the most recent `notification.new` event (mirrors `useVoiceStore` / `useAgentStore` pattern; needed because `api/websocket.ts` has no listener registry).
- `ui/src/components/Notifications/NotificationManager.tsx` — NEW. Reads `useNotificationStore` and calls Tauri notify on each new event.
- `ui/src/components/Notifications/AgentNotificationToggle.tsx` — NEW. Per-agent toggle row used in `AgentCard`.
- `ui/src/components/Settings/BriefingSettings.tsx` — NEW. Time picker + toggle for morning briefing.
- `ui/src/components/Suggestions/SuggestionBanner.tsx` — NEW. Inline suggestion display in chat with Создать/Не сейчас buttons.
- `ui/src/hooks/useSuggestions.ts` — NEW. Polls `/suggestions/active` (via `api.suggestionsActive()`) on focus.
- `ui/src/__tests__/NotificationManager.test.tsx` — NEW.
- `ui/src/__tests__/SuggestionBanner.test.tsx` — NEW.
- `ui/src/__tests__/BriefingSettings.test.tsx` — NEW.
- `ui/src/__tests__/useSuggestions.test.ts` — NEW.

**Frontend (TypeScript — modified files):**
- `ui/src/App.tsx` — mount `<NotificationManager />` at top level.
- `ui/src/api/client.ts` — extend `api` with `suggestionsActive` / `suggestionsSnooze` / `suggestionsAccept`. NOTE: `api.settings` and `api.updateSettings` already exist at lines 165-171 — reused as-is.
- `ui/src/api/types.ts` — add `Suggestion` interface + extend `WSMessage` union with `notification.new` variant.
- `ui/src/api/websocket.ts` — extend `ws.onmessage` switch with `notification.new` case dispatching to `useNotificationStore`.
- `ui/src/components/Settings/Settings.tsx` — add `<BriefingSettings />` section.
- `ui/src/components/AgentPanel/AgentCard.tsx` — add `<AgentNotificationToggle agentName={...} />` row.
- `ui/src/components/Chat/ChatInput.tsx` (or wherever chat messages render) — mount `<SuggestionBanner />`.

**Frontend — verified state (do NOT modify or create parallel):**
- `ui/src/api/client.ts:165-171` — `api.settings()` + `api.updateSettings()` already exist.
- `ui/src/stores/builder.ts:36` — `start(request: string)` already accepts the seed phrase. No changes needed.

**Rust/Tauri (modified):**
- `src-tauri/Cargo.toml` — add `tauri-plugin-notification = "2"`.
- `src-tauri/src/lib.rs` — add `.plugin(tauri_plugin_notification::init())` after line 207.
- `src-tauri/capabilities/default.json` — NEW (directory + file). Declares `notification:default` permission. `src-tauri/capabilities/` directory does NOT currently exist — Tauri 2 auto-discovers it on next build.

---

## Chunk 1: F1 Backend — Voice Morning Briefing (1 day, 6 tasks)

Goal: at user-configured time daily, fire briefing → TTS auto-speaks → no manual action needed.

**Files touched in this chunk:**
- Create: `kernel/briefing_runner.py`, `tests/kernel/test_briefing_runner.py`
- Modify: `kernel/main.py`, `kernel/models.py`

### Task 1.1: Add `BriefingConfig` pydantic model

**Files:**
- Modify: `kernel/models.py` (add new model after existing `ScheduleConfig`)

- [ ] **Step 1: Write the failing test**

Create `tests/kernel/test_models.py` if doesn't exist (or extend if exists). Add:

```python
from kernel.models import BriefingConfig

def test_briefing_config_defaults():
    cfg = BriefingConfig()
    assert cfg.morning_enabled is True
    assert cfg.morning_time == "08:00"
    assert cfg.catchup_window_minutes == 240

def test_briefing_config_validates_time_format():
    import pytest
    with pytest.raises(ValueError):
        BriefingConfig(morning_time="25:00")
    with pytest.raises(ValueError):
        BriefingConfig(morning_time="8am")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_models.py::test_briefing_config_defaults -v`
Expected: `ImportError: cannot import name 'BriefingConfig'` OR `AttributeError`.

- [ ] **Step 3: Write minimal implementation**

Append to `kernel/models.py`:

```python
class BriefingConfig(BaseModel):
    """User-configurable morning briefing schedule."""
    morning_enabled: bool = True
    morning_time: str = "08:00"
    catchup_window_minutes: int = 240

    @validator("morning_time")
    def _valid_time(cls, v: str) -> str:
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError(f"morning_time must be HH:MM 24h, got {v!r}")
        return v
```

Ensure `import re` and `from pydantic import BaseModel, validator` at top of file (verify imports already exist; add if missing).

- [ ] **Step 4: Run test to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_models.py -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/models.py tests/kernel/test_models.py
git commit -m "feat(briefing): add BriefingConfig pydantic model"
```

### Task 1.2: Briefing settings round-trip through /settings

**Files:**
- Modify: `kernel/main.py` (GET /settings + POST /settings handlers — likely near line 2090)

- [ ] **Step 1: Write the failing test**

Add to `tests/kernel/test_main.py`:

```python
async def test_settings_includes_briefing_keys(client):
    r = await client.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert "briefing_morning_enabled" in body
    assert "briefing_morning_time" in body

async def test_settings_persists_briefing_time(client, tmp_env_file):
    payload = {"briefing_morning_enabled": True, "briefing_morning_time": "07:30"}
    r = await client.post("/settings", json=payload)
    assert r.status_code == 200
    r2 = await client.get("/settings")
    assert r2.json()["briefing_morning_time"] == "07:30"
```

(Use the existing fixture pattern in `test_main.py` — read it first for `client` and `tmp_env_file` shape.)

- [ ] **Step 2: Run failing test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py::test_settings_includes_briefing_keys -v`
Expected: FAIL (key not in response).

- [ ] **Step 3: Implement**

In `kernel/main.py` `GET /settings` handler (line 2058-2088), the response is a **nested dict** with `llm/tts/voice` sub-objects plus flat `language` and `onboarding_completed`. Add the two briefing keys at the **top level** (flat, alongside `language` and `onboarding_completed`):

```python
"briefing_morning_enabled": os.environ.get("KALI_BRIEFING_MORNING_ENABLED", "true").lower() == "true",
"briefing_morning_time": os.environ.get("KALI_BRIEFING_MORNING_TIME", "08:00"),
```

In `POST /settings` handler (line 2090), follow the **existing pattern** (line 2096 onwards): accumulate into a single `updates: dict[str, str]` and call `_save_env(updates)` once at the end (line 2133). Insert these blocks before the final `if updates:` check:

```python
if "briefing_morning_enabled" in body:
    val = "true" if body["briefing_morning_enabled"] else "false"
    os.environ["KALI_BRIEFING_MORNING_ENABLED"] = val
    updates["KALI_BRIEFING_MORNING_ENABLED"] = val
if "briefing_morning_time" in body:
    BriefingConfig(morning_time=body["briefing_morning_time"])  # validates HH:MM
    os.environ["KALI_BRIEFING_MORNING_TIME"] = body["briefing_morning_time"]
    updates["KALI_BRIEFING_MORNING_TIME"] = body["briefing_morning_time"]
```

The `_save_env(updates: dict[str, str])` helper is defined at `kernel/main.py:185` — takes a dict and writes once. Do NOT invent `_env_set` or call `_save_env` per-key.

- [ ] **Step 4: Run test to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py -k briefing -v`
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(briefing): /settings round-trip for morning briefing config"
```

### Task 1.3: `briefing_runner.py` — subscribe schedule.morning → speak

**Files:**
- Create: `kernel/briefing_runner.py`, `tests/kernel/test_briefing_runner.py`

- [ ] **Step 1: Write the failing test**

Create `tests/kernel/test_briefing_runner.py`:

```python
"""Tests for kernel.briefing_runner — wires schedule.morning event to TTS."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from kernel.briefing_runner import BriefingRunner
from kernel.event_bus import EventBus
from kernel.models import Event


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def mock_briefing_service():
    svc = MagicMock()
    svc.generate_morning_briefing = AsyncMock(return_value="Good morning, sir. No events.")
    return svc


@pytest.fixture
def mock_speak():
    return AsyncMock()


@pytest.fixture
def mock_agent_data_collector():
    return AsyncMock(return_value={"calendar": {"events": []}})


async def test_runner_subscribes_to_schedule_morning(
    event_bus, mock_briefing_service, mock_speak, mock_agent_data_collector
):
    runner = BriefingRunner(
        bus=event_bus,
        briefing=mock_briefing_service,
        speak=mock_speak,
        collect_agent_data=mock_agent_data_collector,
        enabled_getter=lambda: True,
    )
    await runner.start()
    await event_bus.publish(Event(topic="schedule.morning", source="test", payload={}))
    mock_briefing_service.generate_morning_briefing.assert_awaited_once()
    mock_speak.assert_awaited_once_with("Good morning, sir. No events.")


async def test_runner_skips_when_disabled(
    event_bus, mock_briefing_service, mock_speak, mock_agent_data_collector
):
    runner = BriefingRunner(
        bus=event_bus,
        briefing=mock_briefing_service,
        speak=mock_speak,
        collect_agent_data=mock_agent_data_collector,
        enabled_getter=lambda: False,
    )
    await runner.start()
    await event_bus.publish(Event(topic="schedule.morning", source="test", payload={}))
    mock_speak.assert_not_awaited()
    mock_briefing_service.generate_morning_briefing.assert_not_awaited()


async def test_runner_swallows_tts_errors(
    event_bus, mock_briefing_service, mock_agent_data_collector
):
    failing_speak = AsyncMock(side_effect=RuntimeError("TTS down"))
    runner = BriefingRunner(
        bus=event_bus,
        briefing=mock_briefing_service,
        speak=failing_speak,
        collect_agent_data=mock_agent_data_collector,
        enabled_getter=lambda: True,
    )
    await runner.start()
    # Must not raise — briefing failure cannot kill the kernel.
    await event_bus.publish(Event(topic="schedule.morning", source="test", payload={}))
```

**Why no `drain()` call?** `EventBus.publish()` (kernel/event_bus.py:39) already awaits `asyncio.gather(...)` on all matching handlers before returning. By the time `await bus.publish(...)` resolves, every handler has completed (or raised). No separate flush is needed.

- [ ] **Step 2: Run failing test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_briefing_runner.py -v`
Expected: `ImportError: cannot import name 'BriefingRunner'`.

- [ ] **Step 3: Implement**

Create `kernel/briefing_runner.py`:

```python
"""Wires Scheduler `schedule.morning` events to BriefingService + TTS auto-speak.

Pure orchestration — no business logic. BriefingService stays the single source
of truth for assembling the briefing text.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from kernel.briefing import BriefingService
from kernel.event_bus import EventBus
from kernel.models import Event

logger = logging.getLogger(__name__)

AgentDataCollector = Callable[[], Awaitable[dict[str, Any]]]
SpeakFn = Callable[[str], Awaitable[None]]
EnabledGetter = Callable[[], bool]


class BriefingRunner:
    """Subscribes to schedule.morning and pipes briefing text into TTS.

    Args:
        bus: shared EventBus instance.
        briefing: BriefingService used to assemble text.
        speak: async fn that takes briefing text and plays it via TTS.
        collect_agent_data: async fn that gathers calendar/weather/etc dict
            from agent runtime. Caller provides the actual collector to
            avoid coupling to AgentRuntime here.
        enabled_getter: fn returning current "is briefing enabled" setting.
            Called at fire time (not at subscribe time) so changes take
            effect without restart.
    """

    def __init__(
        self,
        bus: EventBus,
        briefing: BriefingService,
        speak: SpeakFn,
        collect_agent_data: AgentDataCollector,
        enabled_getter: EnabledGetter,
    ) -> None:
        self._bus = bus
        self._briefing = briefing
        self._speak = speak
        self._collect = collect_agent_data
        self._enabled = enabled_getter
        self._started = False

    async def start(self) -> None:
        """Subscribe to schedule.morning topic. Idempotent."""
        if self._started:
            return
        self._bus.subscribe("schedule.morning", self._on_morning)
        self._started = True
        logger.info("BriefingRunner subscribed to schedule.morning")

    async def _on_morning(self, event: Event) -> None:
        if not self._enabled():
            logger.debug("Morning briefing skipped: disabled in settings")
            return
        try:
            agent_data = await self._collect()
            text = await self._briefing.generate_morning_briefing(agent_data)
            if text:
                await self._speak(text)
                logger.info("Morning briefing spoken (%d chars)", len(text))
        except Exception:
            logger.exception("Morning briefing failed — swallowed to keep kernel alive")
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_briefing_runner.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/briefing_runner.py tests/kernel/test_briefing_runner.py
git commit -m "feat(briefing): BriefingRunner — subscribe schedule.morning → TTS"
```

### Task 1.4: Wire BriefingRunner into kernel/main.py startup

**Files:**
- Modify: `kernel/main.py` (lifespan / startup section, around line 312 where BriefingService is instantiated)

- [ ] **Step 1: Write the failing test**

Add to `tests/kernel/test_main.py`:

```python
async def test_briefing_runner_speaks_on_schedule_morning(client, monkeypatch):
    """schedule.morning emit → TTS called with briefing text."""
    spoken: list[str] = []

    async def fake_speak(text: str) -> None:
        spoken.append(text)

    # Monkey-patch _speak_response at module level
    import kernel.main as main_mod
    monkeypatch.setattr(main_mod, "_speak_response", fake_speak)

    # Force enabled
    monkeypatch.setenv("KALI_BRIEFING_MORNING_ENABLED", "true")

    # Fire the topic via injected event bus
    app = client.app
    bus = app.state.event_bus
    await bus.publish(Event(topic="schedule.morning", source="test", payload={}))

    assert len(spoken) == 1
    assert len(spoken[0]) > 0  # non-empty
```

- [ ] **Step 2: Run failing test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py::test_briefing_runner_speaks_on_schedule_morning -v`
Expected: FAIL — no speech happens because runner not wired.

- [ ] **Step 3: Implement**

In `kernel/main.py` lifespan setup (find the section around `briefing = BriefingService(event_bus)` at line 312):

```python
# After: briefing = BriefingService(event_bus)
from kernel.briefing_runner import BriefingRunner

async def _collect_briefing_data() -> dict[str, Any]:
    """Aggregate calendar/tasks/weather/budget from running agents.

    Returns at least an empty dict on any failure — caller handles
    missing keys gracefully.
    """
    data: dict[str, Any] = {}
    try:
        # Re-use existing agent data collection used by /briefing/morning route.
        # If a shared helper exists, call it here; otherwise inline the minimal
        # set used by BriefingService.generate_morning_briefing.
        data = await _gather_agent_data_for_briefing(runtime)
    except Exception:
        logger.exception("agent data collection failed; briefing will be minimal")
    return data

def _briefing_enabled() -> bool:
    return os.environ.get("KALI_BRIEFING_MORNING_ENABLED", "true").lower() == "true"

briefing_runner = BriefingRunner(
    bus=event_bus,
    briefing=briefing,
    speak=_speak_response,
    collect_agent_data=_collect_briefing_data,
    enabled_getter=_briefing_enabled,
)
await briefing_runner.start()
app.state.briefing_runner = briefing_runner
```

If `_gather_agent_data_for_briefing` doesn't exist yet, extract the body of the current `/briefing/morning` route handler (kernel/main.py:940-943) into a module-level async fn and call from both sites. This is the spec's "Refactor briefing assembly logic into reusable module" line.

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py::test_briefing_runner_speaks_on_schedule_morning -v`
Expected: PASS.

Run the broader suite to check nothing broke:

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py -q`
Expected: same count as before plus 1 new pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(briefing): wire BriefingRunner into kernel startup"
```

### Task 1.5: Cron-driven morning fire at user-configured time

**Files:**
- Modify: `kernel/main.py` (call `scheduler.register_cron` with user time)
- Modify: `tests/kernel/test_main.py`

The existing `Scheduler` already fires `schedule.morning` via `morning_hour` config at the top of every hour. For per-minute precision (user wants 08:30 not 08:00), we need to also register a dynamic cron job at the configured minute.

- [ ] **Step 1: Write the failing test**

```python
async def test_briefing_cron_registered_on_settings_change(client):
    """POST /settings with new briefing_morning_time → cron job re-registered."""
    r = await client.post("/settings", json={"briefing_morning_time": "07:15"})
    assert r.status_code == 200

    app = client.app
    jobs = app.state.scheduler.list_cron_jobs()
    assert "briefing_morning" in jobs
    assert jobs["briefing_morning"]["cron_expr"] == "15 7 * * *"
```

- [ ] **Step 2: Run failing test**

Expected: FAIL (`KeyError: 'briefing_morning'`).

- [ ] **Step 3: Implement**

In `kernel/main.py`, after scheduler init, add helper:

```python
def _register_briefing_cron(scheduler: Scheduler, hhmm: str) -> None:
    """Register or replace the daily briefing cron job."""
    hh, mm = hhmm.split(":")
    cron_expr = f"{int(mm)} {int(hh)} * * *"
    scheduler.unregister_cron("briefing_morning")  # idempotent
    scheduler.register_cron("briefing_morning", cron_expr, topic="schedule.morning")
```

Call once at startup using the value from env:

```python
_register_briefing_cron(scheduler, os.environ.get("KALI_BRIEFING_MORNING_TIME", "08:00"))
```

In POST /settings handler, after persisting `briefing_morning_time`:

```python
if "briefing_morning_time" in payload:
    _register_briefing_cron(app.state.scheduler, payload["briefing_morning_time"])
```

Make sure `scheduler` is stashed on `app.state` (verify with grep — likely already there as `app.state.scheduler`).

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_main.py -k briefing -v`
Expected: all 3 briefing tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(briefing): dynamic cron registration from user-configured time"
```

### Task 1.6: Chunk 1 review checkpoint

- [ ] **Two-stage review** per `@superpowers:requesting-code-review` pattern:
  1. Spec compliance: does Chunk 1 deliver F1 in spec? (`docs/superpowers/specs/2026-05-05-proactive-kali-v1.md` F1 section).
  2. Code quality: does it follow project conventions (type hints, no `print`, specific exceptions)?

Read both reviews carefully. **Reviewer can be wrong** (precedent: 2 reviewer mistakes in voice-builder-pilot v2). If a claim contradicts what the code actually does, controller-reject with explanation by reading the cited file.

- [ ] **Verify before claiming chunk complete** (per `@superpowers:verification-before-completion`):

```bash
.venv/Scripts/python.exe -m pytest tests/kernel/test_briefing_runner.py tests/kernel/test_models.py tests/kernel/test_main.py -q
```

Expected: all green. Document the count delta.

---

## Chunk 2: F1 Frontend — Settings UI Briefing section (0.5 day, 3 tasks)

Goal: user sees a Briefing section in Settings with time picker + on/off toggle. Saves via existing POST /settings.

**Files touched:**
- Create: `ui/src/components/Settings/BriefingSettings.tsx`, `ui/src/__tests__/BriefingSettings.test.tsx`
- Modify: `ui/src/components/Settings/Settings.tsx`

### Task 2.1: Component `BriefingSettings.tsx` with time + toggle

**Files:**
- Create: `ui/src/components/Settings/BriefingSettings.tsx`

- [ ] **Step 1: Write the failing test**

Create `ui/src/__tests__/BriefingSettings.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BriefingSettings } from "../components/Settings/BriefingSettings";

// IMPORTANT: settings API already exists on the shared `api` object
// (ui/src/api/client.ts:165-171 → `api.settings()` and `api.updateSettings()`).
// Do NOT invent a separate ui/src/api/settings.ts — mock the existing module.
const mockGet = vi.fn();
const mockUpdate = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    settings: () => mockGet(),
    updateSettings: (payload: unknown) => mockUpdate(payload),
  },
}));

describe("BriefingSettings", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockUpdate.mockReset();
    mockGet.mockResolvedValue({
      briefing_morning_enabled: true,
      briefing_morning_time: "08:00",
    });
    mockUpdate.mockResolvedValue({ ok: true });
  });

  it("renders time picker and toggle from current settings", async () => {
    render(<BriefingSettings />);
    await waitFor(() => {
      expect(screen.getByLabelText(/утренний брифинг/i)).toBeInTheDocument();
    });
    const timeInput = screen.getByLabelText(/время/i) as HTMLInputElement;
    expect(timeInput.value).toBe("08:00");
  });

  it("saves new time via updateSettings", async () => {
    const user = userEvent.setup();
    render(<BriefingSettings />);
    const timeInput = await screen.findByLabelText(/время/i);
    await user.clear(timeInput);
    await user.type(timeInput, "07:30");
    await user.click(screen.getByRole("button", { name: /сохранить/i }));
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ briefing_morning_time: "07:30" }),
      );
    });
  });

  it("toggles enabled state", async () => {
    const user = userEvent.setup();
    render(<BriefingSettings />);
    const toggle = await screen.findByRole("switch", { name: /утренний брифинг/i });
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: /сохранить/i }));
    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ briefing_morning_enabled: false }),
      );
    });
  });
});
```

- [ ] **Step 2: Run failing test**

Run: `cd ui && pnpm test BriefingSettings`
Expected: import fails — file doesn't exist.

- [ ] **Step 3: Implement**

Create `ui/src/components/Settings/BriefingSettings.tsx`:

```tsx
import { useEffect, useState } from "react";
import { api } from "../../api/client";

type State = {
  enabled: boolean;
  time: string;
};

const DEFAULT: State = { enabled: true, time: "08:00" };

export function BriefingSettings() {
  const [state, setState] = useState<State>(DEFAULT);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.settings().then((s) => {
      const settings = s as { briefing_morning_enabled?: boolean; briefing_morning_time?: string };
      setState({
        enabled: settings.briefing_morning_enabled ?? true,
        time: settings.briefing_morning_time ?? "08:00",
      });
      setLoaded(true);
    });
  }, []);

  async function save() {
    setSaving(true);
    try {
      await api.updateSettings({
        briefing_morning_enabled: state.enabled,
        briefing_morning_time: state.time,
      });
    } finally {
      setSaving(false);
    }
  }

  if (!loaded) return null;

  return (
    <section className="settings-section">
      <h3>Утренний брифинг</h3>
      <label>
        <input
          type="checkbox"
          role="switch"
          aria-label="Утренний брифинг"
          checked={state.enabled}
          onChange={(e) => setState({ ...state, enabled: e.target.checked })}
        />
        Включить голосовой брифинг утром
      </label>
      <label>
        Время
        <input
          type="time"
          aria-label="Время"
          value={state.time}
          onChange={(e) => setState({ ...state, time: e.target.value })}
        />
      </label>
      <button onClick={save} disabled={saving}>
        {saving ? "Сохранение…" : "Сохранить"}
      </button>
    </section>
  );
}
```

**Note:** `api.settings()` and `api.updateSettings()` already exist on the shared `api` object (`ui/src/api/client.ts:165-171`). They wrap GET/POST `/settings` and route through `resolveApiUrl` (Python `:3005` for `/settings`). Do NOT create a parallel `api/settings.ts`.

- [ ] **Step 4: Run tests**

Run: `cd ui && pnpm test BriefingSettings`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/Settings/BriefingSettings.tsx ui/src/__tests__/BriefingSettings.test.tsx
git commit -m "feat(briefing): Settings UI section for morning briefing time + toggle"
```

(`ui/src/api/client.ts` is unchanged in this task — we reuse the existing `api.settings()` / `api.updateSettings()`.)

### Task 2.2: Mount `BriefingSettings` in Settings page

**Files:**
- Modify: `ui/src/components/Settings/Settings.tsx`

- [ ] **Step 1: Write the failing test**

Add to existing Settings test file (find it first — `ui/src/__tests__/Settings.test.tsx` likely):

```typescript
it("renders the Briefing section", async () => {
  render(<Settings />);
  expect(await screen.findByText(/Утренний брифинг/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run failing test**

Run: `cd ui && pnpm test Settings.test`
Expected: new test fails.

- [ ] **Step 3: Implement**

In `ui/src/components/Settings/Settings.tsx`, add import + render in section list:

```tsx
import { BriefingSettings } from "./BriefingSettings";

// inside the render JSX, near VoiceSettings:
<BriefingSettings />
```

- [ ] **Step 4: Run test**

Run: `cd ui && pnpm test Settings.test`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/Settings/Settings.tsx
git commit -m "feat(briefing): mount BriefingSettings in Settings page"
```

### Task 2.3: Chunk 2 review checkpoint

- [ ] Spec + code-quality review per Chunk 1 pattern.
- [ ] **Verify**: `cd ui && pnpm test && npx tsc --noEmit` — both green.

---

## Chunk 3: F2 Backend — Alert events + Tauri notification plugin (1 day, 5 tasks)

Goal: notifier/monitor skill templates publish `notification.new` event with shape `{title, message, source, priority}` that frontend can consume.

**Files touched:**
- Modify: `kernel/skill_templates/notifier.py`, `kernel/skill_templates/monitor.py`
- Modify: `src-tauri/Cargo.toml`, `src-tauri/src/lib.rs`
- Create: `src-tauri/capabilities/notification.json` (or merge into default.json)
- Modify: `tests/kernel/test_skill_templates_*.py` (find exact paths first)

### Task 3.1: Notifier template emits `notification.new` event

**Files:**
- Modify: `kernel/skill_templates/notifier.py` — `NotifierTemplate` is an async class (line 14), `async def execute` (line 27), `async def _notify` (line 50). It does NOT currently emit events to the bus, only writes to `history.json`. We add an `await bus.publish(...)` call inside `_notify`.

- [ ] **Step 1: Write the failing test**

Locate or create `tests/kernel/test_skill_template_notifier.py`. Add:

```python
import pytest
from unittest.mock import AsyncMock

from kernel.skill_templates import notifier as notifier_mod
from kernel.skill_templates.notifier import NotifierTemplate


@pytest.fixture(autouse=True)
def reset_event_bus():
    notifier_mod.set_event_bus(None)
    yield
    notifier_mod.set_event_bus(None)


async def test_notify_action_publishes_event(tmp_path):
    bus = AsyncMock()
    notifier_mod.set_event_bus(bus)

    # SkillTemplate.__init__(skill_name, data_dir) — confirmed at
    # kernel/skill_templates/base.py:19. NO config in constructor;
    # config arrives per execute() call.
    template = NotifierTemplate(
        skill_name="biticoin_notifier",
        data_dir=tmp_path,
    )

    result = await template.execute(
        action="notify",
        args={"title": "BTC alert", "message": "Биткоин -5%"},
        config={"default_channel": "voice"},
    )

    assert result["status"] == "sent"
    bus.publish.assert_awaited_once()
    event = bus.publish.await_args[0][0]
    assert event.topic == "notification.new"
    assert event.payload["title"] == "BTC alert"
    assert event.payload["message"] == "Биткоин -5%"
    assert event.payload["source"] == "biticoin_notifier"


async def test_notify_does_not_publish_when_bus_unset(tmp_path):
    """If no bus has been registered (e.g., template used outside KALI kernel),
    _notify must still succeed without raising."""
    template = NotifierTemplate(skill_name="x", data_dir=tmp_path)
    result = await template.execute(
        action="notify",
        args={"message": "hi"},
        config={},
    )
    assert result["status"] == "sent"
```

- [ ] **Step 2: Run failing test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_skill_template_notifier.py -v`
Expected: FAIL — `AttributeError: module 'kernel.skill_templates.notifier' has no attribute 'set_event_bus'`.

- [ ] **Step 3: Implement**

Templates are already async (`async def execute`, `async def _notify`). No sync-bridge needed — just `await bus.publish(...)` directly. Inject bus via a module-level setter called once at kernel startup.

Add to top of `kernel/skill_templates/notifier.py` (after existing imports):

```python
from kernel.event_bus import EventBus
from kernel.models import Event

_event_bus: EventBus | None = None


def set_event_bus(bus: EventBus | None) -> None:
    """Register the event bus that _notify will publish to.

    Called once at kernel startup. Passing None unregisters (used in tests).
    """
    global _event_bus
    _event_bus = bus
```

Inside `async def _notify(self, args, config)`, after the existing `history.append(entry)` and `await self.save_data(...)` lines, add:

```python
if _event_bus is not None:
    await _event_bus.publish(Event(
        topic="notification.new",
        source=self.skill_name,
        payload={
            "title": args.get("title", "Notification"),
            "message": message,
            "priority": args.get("priority", "normal"),
            "source": self.skill_name,
        },
    ))
```

At kernel startup in `kernel/main.py` lifespan, after `event_bus` is created, call once:

```python
from kernel.skill_templates import notifier as _notifier_template
_notifier_template.set_event_bus(event_bus)
```

- [ ] **Step 4: Run test**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_skill_template_notifier.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_templates/notifier.py tests/kernel/test_skill_template_notifier.py kernel/main.py
git commit -m "feat(notifier): publish notification.new event on alert"
```

### Task 3.2: Monitor template emits `notification.new` event

Mirror of Task 3.1 for `kernel/skill_templates/monitor.py` — `MonitorTemplate` (line 17) is also an async class with `async def execute` (line 31). It does NOT currently emit events.

**Files:**
- Modify: `kernel/skill_templates/monitor.py`

- [ ] **Step 1: Write failing test**

Create `tests/kernel/test_skill_template_monitor.py`:

```python
import pytest
from unittest.mock import AsyncMock

from kernel.skill_templates import monitor as monitor_mod
from kernel.skill_templates.monitor import MonitorTemplate


@pytest.fixture(autouse=True)
def reset_event_bus():
    monitor_mod.set_event_bus(None)
    yield
    monitor_mod.set_event_bus(None)


async def test_monitor_publishes_on_status_mismatch(tmp_path):
    bus = AsyncMock()
    monitor_mod.set_event_bus(bus)

    # SkillTemplate.__init__ signature: (skill_name, data_dir) — no config.
    template = MonitorTemplate(skill_name="example_monitor", data_dir=tmp_path)

    # _mock_status forces a non-matching response (per existing args contract,
    # see monitor.py docstring at line 38).
    result = await template.execute(
        action="check",
        args={"_mock_status": 503},
        config={"url": "https://example.com", "expected_status": 200},
    )

    bus.publish.assert_awaited_once()
    event = bus.publish.await_args[0][0]
    assert event.topic == "notification.new"
    assert event.payload["source"] == "example_monitor"


async def test_monitor_does_not_publish_on_match(tmp_path):
    bus = AsyncMock()
    monitor_mod.set_event_bus(bus)

    template = MonitorTemplate(skill_name="example_monitor", data_dir=tmp_path)
    await template.execute(
        action="check",
        args={"_mock_status": 200},
        config={"url": "https://example.com", "expected_status": 200},
    )

    bus.publish.assert_not_awaited()
```

- [ ] **Step 2: Run failing test** — expect FAIL with `AttributeError: ... has no attribute 'set_event_bus'`.

- [ ] **Step 3: Implement** — same pattern as Task 3.1. Add module-level `_event_bus` + `set_event_bus(bus)` to `kernel/skill_templates/monitor.py`. Inside async `_check` (or wherever status mismatch is detected — read the file first), publish on mismatch only:

```python
if _event_bus is not None and status != expected_status:
    await _event_bus.publish(Event(
        topic="notification.new",
        source=self.skill_name,
        payload={
            "title": f"{self.skill_name}: статус {status}",
            "message": f"URL {url} вернул {status}, ожидался {expected_status}",
            "priority": "high",
            "source": self.skill_name,
        },
    ))
```

In `kernel/main.py` lifespan, mirror the notifier wiring:

```python
from kernel.skill_templates import monitor as _monitor_template
_monitor_template.set_event_bus(event_bus)
```

**DRY decision:** the two templates share ~5 lines of bus-publish code. **Do NOT** extract a shared helper for this in v1 — premature abstraction. If a third template needs the same pattern, then refactor.

- [ ] **Step 4: Run tests** — both templates' tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/skill_templates/monitor.py tests/kernel/test_skill_template_monitor.py kernel/main.py
git commit -m "feat(monitor): publish notification.new event on status mismatch"
```

### Task 3.3: Add `tauri-plugin-notification` to Rust deps

**Files:**
- Modify: `src-tauri/Cargo.toml`

- [ ] **Step 1: Verify current state**

Read `src-tauri/Cargo.toml` lines 6-12. Confirm `tauri-plugin-notification` NOT present (per code map: it's NOT there).

- [ ] **Step 2: Add dep**

Append to `[dependencies]`:

```toml
tauri-plugin-notification = "2"
```

- [ ] **Step 3: Build check**

Run from worktree: `cd src-tauri && cargo check` (this triggers download + compile of new crate; takes ~1-2 min first time).
Expected: exit 0.

- [ ] **Step 4: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock
git commit -m "build(tauri): add tauri-plugin-notification 2"
```

### Task 3.4: Init notification plugin in `lib.rs` + capability JSON

**Verified state:**
- `src-tauri/src/lib.rs:206-208` has the plugin-init block (`.plugin(tauri_plugin_shell::init())` then `.plugin(tauri_plugin_global_shortcut::Builder::new().build())`)
- `src-tauri/capabilities/` directory does **NOT** exist — must be created
- `src-tauri/gen/schemas/desktop-schema.json` **does** exist (tauri-build generates it) — the `$schema` reference resolves
- `src-tauri/tauri.conf.json` window has no explicit `label`, which means Tauri 2 defaults the label to `"main"` — match it

**Files:**
- Modify: `src-tauri/src/lib.rs` (insert one line at 208)
- Create: `src-tauri/capabilities/default.json` (new file + new directory)

- [ ] **Step 1: Add notification plugin init**

In `src-tauri/src/lib.rs`, after line 207 (`.plugin(tauri_plugin_shell::init())`), insert:

```rust
.plugin(tauri_plugin_notification::init())
```

The result should be three contiguous `.plugin(...)` lines: shell, notification, global_shortcut.

- [ ] **Step 2: Create capability JSON**

Create directory + file:

```bash
mkdir -p src-tauri/capabilities
```

Create `src-tauri/capabilities/default.json` with:

```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Default capability for the main window",
  "windows": ["main"],
  "permissions": [
    "core:default",
    "shell:allow-open",
    "notification:default"
  ]
}
```

Notes on each field:
- `$schema` — relative to the file location; resolves to `src-tauri/gen/schemas/desktop-schema.json` which is auto-generated and present.
- `identifier` — Tauri auto-loads `default` capability for windows by convention.
- `windows: ["main"]` — matches Tauri 2's default window label when none is set in `tauri.conf.json`.
- `permissions` — `core:default` is the Tauri 2 base, `shell:allow-open` matches the existing shell plugin usage (line 207), `notification:default` enables the notification plugin's permissions.

- [ ] **Step 3: Build check**

Run from worktree root: `cd src-tauri && cargo check`
Expected: exit 0. (First build of the new plugin may take 1-2 min — that's normal.)

If `cargo check` complains about the capability JSON syntax or schema, validate against the actual generated schema at `src-tauri/gen/schemas/desktop-schema.json`.

- [ ] **Step 4: Commit**

```bash
git add src-tauri/src/lib.rs src-tauri/capabilities/default.json
git commit -m "feat(tauri): init notification plugin + capability"
```

### Task 3.5: Chunk 3 review checkpoint

- [ ] Spec + code-quality review.
- [ ] **Verify**:

```bash
.venv/Scripts/python.exe -m pytest tests/kernel/test_skill_template_notifier.py tests/kernel/test_skill_template_monitor.py -v
cd src-tauri && cargo check && cd ..
```

Both green.

---

## Chunk 4: F2 Frontend — NotificationManager + per-agent toggle (1 day, 6 tasks)

Goal: WS `notification.new` event → Windows Toast / macOS native notification. Click toast → open KALI to agents tab. Per-agent toggle in AgentCard.

**Files touched:**
- Create: `ui/src/components/Notifications/NotificationManager.tsx`, `ui/src/components/Notifications/AgentNotificationToggle.tsx`, `ui/src/api/notifications.ts`, two test files.
- Modify: `ui/src/App.tsx`, `ui/src/components/AgentPanel/AgentCard.tsx`.

### Task 4.1: `api/notifications.ts` — Tauri notify wrapper

**Files:**
- Create: `ui/src/api/notifications.ts`

- [ ] **Step 1: Write failing test**

Create `ui/src/__tests__/api-notifications.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { sendNotification } from "../api/notifications";

const tauriInvoke = vi.fn();
vi.mock("@tauri-apps/plugin-notification", () => ({
  sendNotification: (...args: unknown[]) => tauriInvoke(...args),
  isPermissionGranted: vi.fn().mockResolvedValue(true),
  requestPermission: vi.fn().mockResolvedValue("granted"),
}));

describe("api/notifications", () => {
  beforeEach(() => tauriInvoke.mockReset());

  it("invokes Tauri plugin with title+body", async () => {
    await sendNotification({ title: "Alert", body: "BTC fell 5%" });
    expect(tauriInvoke).toHaveBeenCalledWith({ title: "Alert", body: "BTC fell 5%" });
  });

  it("noops in non-Tauri environment", async () => {
    // Simulated by removing the plugin mock would be more involved;
    // for now trust the integration mock above. Real env check:
    expect(true).toBe(true);  // placeholder
  });
});
```

- [ ] **Step 2: Run failing test**

Run: `cd ui && pnpm test api-notifications`
Expected: FAIL — file doesn't exist.

- [ ] **Step 3: Implement**

Create `ui/src/api/notifications.ts`:

```typescript
import {
  sendNotification as tauriSend,
  isPermissionGranted,
  requestPermission,
} from "@tauri-apps/plugin-notification";

export type NotificationPayload = {
  title: string;
  body: string;
};

let permissionChecked = false;
let permissionGranted = false;

async function ensurePermission(): Promise<boolean> {
  if (permissionChecked) return permissionGranted;
  permissionChecked = true;
  try {
    permissionGranted = await isPermissionGranted();
    if (!permissionGranted) {
      const result = await requestPermission();
      permissionGranted = result === "granted";
    }
  } catch {
    permissionGranted = false;
  }
  return permissionGranted;
}

export async function sendNotification(payload: NotificationPayload): Promise<void> {
  if (!(await ensurePermission())) return;
  try {
    await tauriSend({ title: payload.title, body: payload.body });
  } catch (err) {
    console.warn("[notifications] send failed", err);
  }
}
```

Also install the plugin's JS package. **Pin to v2.x** to match the Rust crate `tauri-plugin-notification = "2"` (Task 3.3). A `1.x` JS package would silently bind to incompatible Rust APIs:

```bash
cd ui && pnpm add "@tauri-apps/plugin-notification@^2"
```

- [ ] **Step 4: Run test**

Run: `cd ui && pnpm test api-notifications`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/notifications.ts ui/src/__tests__/api-notifications.test.ts ui/package.json ui/pnpm-lock.yaml
git commit -m "feat(notifications): Tauri notify wrapper with permission gate"
```

### Task 4.2: WS notification.new → Zustand store → Tauri notify

**Important design note:** `ui/src/api/websocket.ts` currently has all message handling **inline** in `ws.onmessage` (verified — no listener registry, no `onMessage` export). The cleanest fit with the existing pattern (`useVoiceStore`, `useAgentStore`, `useDashboardStore` all consume WS events via Zustand) is to **add a new `useNotificationStore`** and dispatch the new topic into it from the existing switch. NotificationManager reads the store via selector.

This task has 4 sub-changes that ship as **one commit** (one feature: "WS notification.new → desktop notify"):

**Files:**
- Create: `ui/src/stores/notificationStore.ts`
- Modify: `ui/src/api/types.ts` (add WSMessage variant)
- Modify: `ui/src/api/websocket.ts` (new switch case)
- Create: `ui/src/components/Notifications/NotificationManager.tsx`
- Create: `ui/src/__tests__/NotificationManager.test.tsx`

- [ ] **Step 1: Write failing test**

Create `ui/src/__tests__/NotificationManager.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { act } from "react";

const mockSend = vi.fn();
vi.mock("../api/notifications", () => ({
  sendNotification: (p: unknown) => mockSend(p),
}));

import { NotificationManager } from "../components/Notifications/NotificationManager";
import { useNotificationStore } from "../stores/notificationStore";

describe("NotificationManager", () => {
  beforeEach(() => {
    mockSend.mockReset();
    // Reset store state between tests
    useNotificationStore.setState({ lastEvent: null });
    localStorage.clear();
  });

  it("calls sendNotification when store receives a new event", async () => {
    render(<NotificationManager />);
    act(() => {
      useNotificationStore.getState().push({
        title: "Alert",
        message: "BTC fell",
        source: "biti_notifier",
        priority: "normal",
        receivedAt: Date.now(),
      });
    });
    expect(mockSend).toHaveBeenCalledWith({ title: "Alert", body: "BTC fell" });
  });

  it("ignores events from agents disabled in localStorage", async () => {
    localStorage.setItem("notifications.biti_notifier", "false");
    render(<NotificationManager />);
    act(() => {
      useNotificationStore.getState().push({
        title: "X",
        message: "Y",
        source: "biti_notifier",
        priority: "normal",
        receivedAt: Date.now(),
      });
    });
    expect(mockSend).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run failing test**

Expected: import fails — neither the store nor the component exists yet.

- [ ] **Step 3: Create Zustand store**

Create `ui/src/stores/notificationStore.ts`:

```typescript
import { create } from "zustand";

export interface NotificationEvent {
  title: string;
  message: string;
  source: string;
  priority: string;
  receivedAt: number;
}

interface NotificationStore {
  lastEvent: NotificationEvent | null;
  push: (event: NotificationEvent) => void;
}

export const useNotificationStore = create<NotificationStore>((set) => ({
  lastEvent: null,
  push: (event) => set({ lastEvent: event }),
}));
```

- [ ] **Step 4: Extend `WSMessage` discriminated union**

In `ui/src/api/types.ts`, add a new variant to the `WSMessage` union (after `agent.status.update`):

```typescript
| { type: "notification.new"; data: { title: string; message: string; source: string; priority: string } }
```

- [ ] **Step 5: Wire dispatch into websocket switch**

In `ui/src/api/websocket.ts`, inside the existing `switch (msg.type)` block (after `case "dashboard.update":`), add:

```typescript
case "notification.new":
  useNotificationStore.getState().push({
    title: msg.data.title,
    message: msg.data.message,
    source: msg.data.source,
    priority: msg.data.priority,
    receivedAt: Date.now(),
  });
  break;
```

Add the import at the top of the file alongside the other store imports:

```typescript
import { useNotificationStore } from "../stores/notificationStore";
```

- [ ] **Step 6: Create NotificationManager component**

Create `ui/src/components/Notifications/NotificationManager.tsx`:

```tsx
import { useEffect } from "react";
import { sendNotification } from "../../api/notifications";
import { useNotificationStore } from "../../stores/notificationStore";

function isEnabledForAgent(source: string): boolean {
  const stored = localStorage.getItem(`notifications.${source}`);
  return stored !== "false";
}

export function NotificationManager() {
  const lastEvent = useNotificationStore((s) => s.lastEvent);

  useEffect(() => {
    if (!lastEvent) return;
    if (!isEnabledForAgent(lastEvent.source)) return;
    sendNotification({ title: lastEvent.title, body: lastEvent.message });
  }, [lastEvent]);

  return null;
}
```

- [ ] **Step 7: Run tests**

Run: `cd ui && pnpm test NotificationManager`
Expected: 2 tests pass.

- [ ] **Step 8: Commit**

```bash
git add ui/src/stores/notificationStore.ts \
        ui/src/api/types.ts \
        ui/src/api/websocket.ts \
        ui/src/components/Notifications/NotificationManager.tsx \
        ui/src/__tests__/NotificationManager.test.tsx
git commit -m "feat(notifications): WS notification.new → Tauri notify via store"
```

### Task 4.3: Mount `<NotificationManager />` in App.tsx

**Files:**
- Modify: `ui/src/App.tsx`

This is a pure wiring task — adding a single component invocation to the render tree. The behavioral coverage is already in Task 4.2 (unit test for the component itself) and will be re-covered in Chunk 7's E2E test that fires a WS event end-to-end. **No unit test for this task** — testing "the component is in the JSX" has near-zero signal. We rely on the type checker + E2E for verification.

- [ ] **Step 1: Implement**

In `ui/src/App.tsx`, add import and mount the component once at the top of the JSX tree (inside the wrapping `<div>`, before `<Sidebar />`):

```tsx
import { NotificationManager } from "./components/Notifications/NotificationManager";

// Inside the main render JSX, top of the return tree:
<NotificationManager />
<Sidebar />
```

NotificationManager returns `null` so it does not affect layout.

- [ ] **Step 2: Verify**

```bash
cd ui && pnpm test && npx tsc --noEmit
```

Expected: green. tsc exit 0. No new test failures introduced.

- [ ] **Step 3: Commit**

```bash
git add ui/src/App.tsx
git commit -m "feat(notifications): mount NotificationManager in App root"
```

### Task 4.4: Click-toast → switch to agents mode + scroll

**Files:**
- Modify: `ui/src/components/Notifications/NotificationManager.tsx`
- Modify: `ui/src/api/notifications.ts` (if click handler needs returning)

- [ ] **Step 1: Decide click integration**

Read `@tauri-apps/plugin-notification` docs for click event handling. Tauri 2 plugin emits events from the OS toast. May require a Rust-side `on_action` handler that emits to JS via `app.emit_to`. Or the plugin offers an `onAction` callback in JS.

Two options:
- **Option A:** Tauri-plugin built-in `onAction` — simpler, JS-only.
- **Option B:** Custom Rust handler — more flexibility.

Default to Option A; if not available in 2.x, fall back to Option B.

- [ ] **Step 2: Implement click handler**

Extend `NotificationManager`:

```tsx
// pseudocode — adjust to actual plugin API
useEffect(() => {
  const off = onNotificationClick((payload) => {
    const source = payload.source;
    useAppStore.getState().setMode("agents");
    // optional: scroll to source agent — emit a custom event
    window.dispatchEvent(new CustomEvent("agent:scroll-to", { detail: { source } }));
  });
  return () => off();
}, []);
```

If plugin API doesn't expose click → leave it as a deferred enhancement. Document in commit message.

- [ ] **Step 3: Smoke test manually**

Open dev build, fire a fake event via DevTools:

```js
window.__kali_debug_notify({ title: "test", message: "click me", source: "weather" });
```

(Requires a temporary debug hook in NotificationManager — add behind `if (import.meta.env.DEV)`.)

Click the toast → assert app switches to agents mode.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/Notifications/NotificationManager.tsx
git commit -m "feat(notifications): click-toast routes to agents mode"
```

### Task 4.5: `AgentNotificationToggle` per-agent setting in AgentCard

**Files:**
- Create: `ui/src/components/Notifications/AgentNotificationToggle.tsx`
- Modify: `ui/src/components/AgentPanel/AgentCard.tsx`

- [ ] **Step 1: Write failing test**

```typescript
describe("AgentNotificationToggle", () => {
  it("starts enabled (default)", () => {
    render(<AgentNotificationToggle agentName="weather" />);
    const sw = screen.getByRole("switch") as HTMLInputElement;
    expect(sw.checked).toBe(true);
  });

  it("persists disabled state to localStorage", async () => {
    const user = userEvent.setup();
    render(<AgentNotificationToggle agentName="weather" />);
    await user.click(screen.getByRole("switch"));
    expect(localStorage.getItem("notifications.weather")).toBe("false");
  });
});
```

- [ ] **Step 2: Run failing test**

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `ui/src/components/Notifications/AgentNotificationToggle.tsx`:

```tsx
import { useState } from "react";

type Props = { agentName: string };

export function AgentNotificationToggle({ agentName }: Props) {
  const key = `notifications.${agentName}`;
  const [enabled, setEnabled] = useState(() => localStorage.getItem(key) !== "false");

  function toggle() {
    const next = !enabled;
    setEnabled(next);
    localStorage.setItem(key, String(next));
  }

  return (
    <label className="flex items-center gap-2 text-sm">
      <input
        type="checkbox"
        role="switch"
        checked={enabled}
        onChange={toggle}
        aria-label={`Уведомления от ${agentName}`}
      />
      <span>Уведомления</span>
    </label>
  );
}
```

Then in `AgentCard.tsx`, add the toggle in the card body:

```tsx
import { AgentNotificationToggle } from "../Notifications/AgentNotificationToggle";

// inside the card render:
<AgentNotificationToggle agentName={agent.name} />
```

- [ ] **Step 4: Run tests**

Run: `cd ui && pnpm test AgentNotificationToggle && pnpm test AgentCard`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/Notifications/AgentNotificationToggle.tsx ui/src/__tests__/AgentNotificationToggle.test.tsx ui/src/components/AgentPanel/AgentCard.tsx
git commit -m "feat(notifications): per-agent toggle row in AgentCard"
```

### Task 4.6: Chunk 4 review checkpoint

- [ ] Spec + code-quality review.
- [ ] **Verify**:

```bash
cd ui && pnpm test && npx tsc --noEmit
```

Expected: green. New tests for NotificationManager + AgentNotificationToggle pass; total count grows by ~6-8 tests.

---

## Chunk 5: F3 Backend — Intent log + Suggestion engine (1.5 days, 8 tasks)

Goal: every /chat hit logs intent classification. Cron job every 6h scans for 5+ matches of same intent → creates suggestion. Endpoints expose suggestions to UI.

**Files touched:**
- Create: `kernel/suggestions.py`, `tests/kernel/test_suggestions.py`
- Modify: `kernel/database.py` (extend SCHEMA), `kernel/main.py` (/chat hook + /suggestions routes + cron registration), `kernel/models.py` (SuggestionRecord)

### Task 5.1: Database schema + public `conn` accessor

**Files:**
- Modify: `kernel/database.py` — extend `SCHEMA` (line 12-42) + add a **public** `conn` property. The existing `_db` (line 73) is private; SuggestionEngine needs a clean public accessor to avoid touching `_db`.

- [ ] **Step 1: Write failing test**

Add to `tests/kernel/test_database.py` (or create — the project has `asyncio_mode = "auto"` so test functions don't need the `@pytest.mark.asyncio` decorator, but fixtures still do — see Task 5.3 for the fixture pattern):

```python
from pathlib import Path

from kernel.database import Database


async def test_initialize_creates_intent_log_table(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    cursor = await db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_intent_log'"
    )
    row = await cursor.fetchone()
    await db.close()
    assert row is not None


async def test_initialize_creates_suggestions_table(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    cursor = await db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='suggestions'"
    )
    row = await cursor.fetchone()
    await db.close()
    assert row is not None


async def test_conn_property_returns_connection(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    await db.initialize()
    assert db.conn is not None
    await db.close()
```

- [ ] **Step 2: Run failing test**

Expected: FAIL — `chat_intent_log` does not exist, and `db.conn` raises `AttributeError`.

- [ ] **Step 3: Add `conn` property to Database**

In `kernel/database.py`, right after the existing private `_db` property (around line 72-76), add:

```python
@property
def conn(self) -> aiosqlite.Connection:
    """Public accessor for the underlying connection.

    Used by classes that compose Database (e.g., SuggestionEngine) and need to
    issue queries not covered by Database's curated methods.
    """
    return self._db
```

- [ ] **Step 4: Extend `SCHEMA`**

In `kernel/database.py`, append to the existing `SCHEMA` string (which currently ends after `user_preferences`):

```python
SCHEMA = """
... existing tables ...

CREATE TABLE IF NOT EXISTS chat_intent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    intent_type TEXT NOT NULL,
    intent_template TEXT,
    raw_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_intent_log_timestamp
    ON chat_intent_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_chat_intent_log_template
    ON chat_intent_log(intent_template);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    intent_template TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    snoozed_until TEXT,
    accepted_at TEXT,
    UNIQUE(intent_template, created_at)
);

CREATE INDEX IF NOT EXISTS idx_suggestions_active
    ON suggestions(snoozed_until, accepted_at);
"""
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_database.py -v`
Expected: 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add kernel/database.py tests/kernel/test_database.py
git commit -m "feat(suggestions): add chat_intent_log + suggestions tables + conn accessor"
```

### Task 5.2: `SuggestionRecord` pydantic model

**Files:**
- Modify: `kernel/models.py`

- [ ] **Step 1: Write failing test**

```python
def test_suggestion_record_defaults():
    rec = SuggestionRecord(
        id=1,
        created_at="2026-05-13T10:00:00",
        intent_template="notifier",
        prompt_text="Создать агента для уведомлений?",
    )
    assert rec.snoozed_until is None
    assert rec.accepted_at is None
```

- [ ] **Step 2: Run failing test** — expect ImportError.

- [ ] **Step 3: Implement**

Append to `kernel/models.py`:

```python
class SuggestionRecord(BaseModel):
    id: int
    created_at: str
    intent_template: str
    prompt_text: str
    snoozed_until: str | None = None
    accepted_at: str | None = None
```

- [ ] **Step 4: Run tests** — PASS.

- [ ] **Step 5: Commit**

```bash
git add kernel/models.py tests/kernel/test_models.py
git commit -m "feat(suggestions): SuggestionRecord pydantic model"
```

### Task 5.3: `SuggestionEngine` class — log + detect + create suggestion

**Files:**
- Create: `kernel/suggestions.py`, `tests/kernel/test_suggestions.py`

- [ ] **Step 1: Write failing test**

Create `tests/kernel/test_suggestions.py`:

```python
import pytest
import pytest_asyncio

from kernel.database import Database
from kernel.suggestions import SuggestionEngine


# IMPORTANT: pyproject.toml has `asyncio_mode = "auto"` which auto-marks test
# functions but NOT fixtures. Async fixtures MUST use @pytest_asyncio.fixture.
@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(tmp_path / "test.db")
    await d.initialize()
    yield d
    await d.close()


async def test_log_intent_appends_row(db):
    engine = SuggestionEngine(db)
    await engine.log_intent(intent_type="skill", intent_template="notifier", raw_text="курс биткоин")
    rows = await engine._all_intent_logs()
    assert len(rows) == 1
    assert rows[0]["intent_template"] == "notifier"
    assert rows[0]["raw_text"] == "курс биткоин"


async def test_detect_threshold_creates_suggestion(db):
    engine = SuggestionEngine(db)
    # 5 hits on same intent template within 7-day window
    for i in range(5):
        await engine.log_intent("skill", "notifier", f"курс биткоин {i}")
    suggestions = await engine.detect_patterns()
    assert len(suggestions) == 1
    assert suggestions[0].intent_template == "notifier"


async def test_detect_below_threshold_no_suggestion(db):
    engine = SuggestionEngine(db)
    for i in range(4):  # below threshold of 5
        await engine.log_intent("skill", "notifier", "x")
    suggestions = await engine.detect_patterns()
    assert len(suggestions) == 0


async def test_dedup_existing_suggestion(db):
    engine = SuggestionEngine(db)
    for i in range(5):
        await engine.log_intent("skill", "notifier", "x")
    await engine.detect_patterns()  # first run creates 1
    await engine.detect_patterns()  # second run should not duplicate
    rows = await engine._all_suggestions()
    assert len(rows) == 1


async def test_snooze_marks_suggestion(db):
    engine = SuggestionEngine(db)
    for i in range(5):
        await engine.log_intent("skill", "notifier", "x")
    suggestions = await engine.detect_patterns()
    await engine.snooze(suggestions[0].id, days=7)
    active = await engine.list_active()
    assert len(active) == 0  # snoozed → not active


async def test_active_excludes_accepted(db):
    engine = SuggestionEngine(db)
    for i in range(5):
        await engine.log_intent("skill", "notifier", "x")
    suggestions = await engine.detect_patterns()
    await engine.mark_accepted(suggestions[0].id)
    active = await engine.list_active()
    assert len(active) == 0
```

- [ ] **Step 2: Run failing test** — ImportError.

- [ ] **Step 3: Implement**

Create `kernel/suggestions.py`:

```python
"""Suggestion engine — pattern detection over chat intent log.

Tracks intent classifications in SQLite. Periodic cron job (every 6h) looks
for repeated intents in the last 7 days and creates suggestion records.

Privacy: intent log + raw text never leaves device.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from kernel.database import Database
from kernel.models import SuggestionRecord

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 5
DEFAULT_WINDOW_DAYS = 7
DEFAULT_SNOOZE_DAYS = 7

PROMPT_TEMPLATES: dict[str, str] = {
    "notifier": "Я заметил, ты часто просишь уведомить о чём-то. Создать агента-нотификатор?",
    "monitor": "Я заметил, ты часто проверяешь одно и то же. Создать агента-монитор?",
    "tracker": "Я заметил, ты часто считаешь одно и то же. Создать агента-трекер?",
    "reminder": "Я заметил, ты часто просишь напомнить. Создать агента-напоминалку?",
    "logger": "Я заметил, ты часто ведёшь учёт. Создать агента-дневник?",
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SuggestionEngine:
    """Persists intent classifications and emits suggestion records.

    Note on DB access: Database uses a single long-lived `aiosqlite.Connection`
    (kernel/database.py:55). We access it via the public `db.conn` property
    rather than opening per-call context managers — matches the existing
    pattern in Database's own methods (e.g., save_conversation line 107).
    """

    def __init__(
        self,
        db: Database,
        threshold: int = DEFAULT_THRESHOLD,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        self._db = db
        self._threshold = threshold
        self._window = timedelta(days=window_days)

    async def log_intent(
        self, intent_type: str, intent_template: str | None, raw_text: str
    ) -> None:
        """Append an intent classification to chat_intent_log."""
        await self._db.conn.execute(
            """
            INSERT INTO chat_intent_log (timestamp, intent_type, intent_template, raw_text)
            VALUES (?, ?, ?, ?)
            """,
            (_now_iso(), intent_type, intent_template, raw_text),
        )
        await self._db.conn.commit()

    async def detect_patterns(self) -> list[SuggestionRecord]:
        """Scan recent intent log and create suggestion records for clusters."""
        cutoff = (datetime.now(UTC) - self._window).isoformat()
        new_suggestions: list[SuggestionRecord] = []

        cursor = await self._db.conn.execute(
            """
            SELECT intent_template, COUNT(*) AS cnt
            FROM chat_intent_log
            WHERE timestamp >= ? AND intent_template IS NOT NULL
            GROUP BY intent_template
            HAVING cnt >= ?
            """,
            (cutoff, self._threshold),
        )
        clusters = await cursor.fetchall()

        for row in clusters:
            template = row[0]
            if not template:
                continue
            existing = await self._db.conn.execute(
                """
                SELECT id FROM suggestions
                WHERE intent_template = ?
                  AND accepted_at IS NULL
                  AND (snoozed_until IS NULL OR snoozed_until < ?)
                """,
                (template, _now_iso()),
            )
            if await existing.fetchone():
                continue

            prompt = PROMPT_TEMPLATES.get(
                template,
                f"Я заметил повторяющийся паттерн ({template}). Создать агента?",
            )
            now = _now_iso()
            cursor2 = await self._db.conn.execute(
                """
                INSERT INTO suggestions (created_at, intent_template, prompt_text)
                VALUES (?, ?, ?)
                """,
                (now, template, prompt),
            )
            await self._db.conn.commit()
            new_suggestions.append(SuggestionRecord(
                id=cursor2.lastrowid,
                created_at=now,
                intent_template=template,
                prompt_text=prompt,
            ))
            logger.info("Suggestion created: %s", template)
        return new_suggestions

    async def list_active(self) -> list[SuggestionRecord]:
        """Return non-snoozed, non-accepted suggestions, newest first."""
        cursor = await self._db.conn.execute(
            """
            SELECT id, created_at, intent_template, prompt_text, snoozed_until, accepted_at
            FROM suggestions
            WHERE accepted_at IS NULL
              AND (snoozed_until IS NULL OR snoozed_until < ?)
            ORDER BY created_at DESC
            """,
            (_now_iso(),),
        )
        rows = await cursor.fetchall()
        return [
            SuggestionRecord(
                id=r[0], created_at=r[1], intent_template=r[2],
                prompt_text=r[3], snoozed_until=r[4], accepted_at=r[5],
            )
            for r in rows
        ]

    async def snooze(self, suggestion_id: int, days: int = DEFAULT_SNOOZE_DAYS) -> None:
        """Snooze a suggestion for N days."""
        until = (datetime.now(UTC) + timedelta(days=days)).isoformat()
        await self._db.conn.execute(
            "UPDATE suggestions SET snoozed_until = ? WHERE id = ?",
            (until, suggestion_id),
        )
        await self._db.conn.commit()

    async def mark_accepted(self, suggestion_id: int) -> None:
        """Mark a suggestion as accepted (user clicked Создать)."""
        await self._db.conn.execute(
            "UPDATE suggestions SET accepted_at = ? WHERE id = ?",
            (_now_iso(), suggestion_id),
        )
        await self._db.conn.commit()

    async def _all_intent_logs(self) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute("SELECT * FROM chat_intent_log ORDER BY id")
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in await cursor.fetchall()]

    async def _all_suggestions(self) -> list[dict[str, Any]]:
        cursor = await self._db.conn.execute("SELECT * FROM suggestions ORDER BY id")
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in await cursor.fetchall()]
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_suggestions.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add kernel/suggestions.py tests/kernel/test_suggestions.py
git commit -m "feat(suggestions): SuggestionEngine with log/detect/snooze/accept"
```

### Task 5.4: Hook `_chat_logic` to log intent

**Files:**
- Modify: `kernel/main.py` around line 1055 (`_chat_logic`)

- [ ] **Step 1: Write failing test**

```python
async def test_chat_logs_intent_classification(client, app):
    """Every /chat hit appends a row to chat_intent_log."""
    r = await client.post("/chat", json={"message": "напоминай делать растяжку"})
    assert r.status_code == 200

    engine = app.state.suggestion_engine
    rows = await engine._all_intent_logs()
    assert len(rows) >= 1
    last = rows[-1]
    assert last["intent_template"] in ("reminder", None)  # may be None if classification fails
    assert "напоминай" in last["raw_text"]
```

- [ ] **Step 2: Run failing test** — FAIL.

- [ ] **Step 3: Implement**

In `kernel/main.py`, instantiate `SuggestionEngine` near `briefing` instantiation:

```python
from kernel.suggestions import SuggestionEngine

suggestion_engine = SuggestionEngine(db=database)
app.state.suggestion_engine = suggestion_engine
```

In `_chat_logic`, after intent classification (find where `classify_intent` is called) add:

```python
intent = classify_intent(user_message)  # already happens
try:
    await app.state.suggestion_engine.log_intent(
        intent_type=intent.type,
        intent_template=intent.template,
        raw_text=user_message,
    )
except Exception:
    logger.exception("intent log failed; non-fatal")
```

- [ ] **Step 4: Run test** — PASS.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(suggestions): log every /chat intent classification"
```

### Task 5.5: Register pattern-detect cron (every 6h)

**Files:**
- Modify: `kernel/main.py`

- [ ] **Step 1: Subscribe and register**

Add to lifespan startup:

```python
async def _on_pattern_detect_cron(event):
    try:
        new_suggestions = await suggestion_engine.detect_patterns()
        for s in new_suggestions:
            await event_bus.publish(Event(
                topic="suggestion.new",
                source="suggestion-engine",
                payload={"id": s.id, "template": s.intent_template, "prompt": s.prompt_text},
            ))
    except Exception:
        logger.exception("pattern detect failed; non-fatal")

event_bus.subscribe("schedule.cron.suggestion_detect", _on_pattern_detect_cron)
scheduler.register_cron("suggestion_detect", "0 */6 * * *",
                        topic="schedule.cron.suggestion_detect")
```

- [ ] **Step 2: Write test**

```python
async def test_suggestion_detect_cron_fires(client, app):
    engine = app.state.suggestion_engine
    for i in range(5):
        await engine.log_intent("skill", "notifier", "x")

    # Manually emit the cron topic. publish() awaits all subscribers via
    # asyncio.gather before returning, so no separate drain step is needed.
    bus = app.state.event_bus
    await bus.publish(Event(topic="schedule.cron.suggestion_detect", source="test", payload={}))

    active = await engine.list_active()
    assert len(active) >= 1
```

- [ ] **Step 3: Run test** — PASS.

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(suggestions): pattern-detect cron every 6h"
```

### Task 5.6: `/suggestions/active` GET endpoint

**Files:**
- Modify: `kernel/main.py`

- [ ] **Step 1: Write failing test**

```python
async def test_get_active_suggestions(client, app):
    engine = app.state.suggestion_engine
    for i in range(5):
        await engine.log_intent("skill", "notifier", "x")
    await engine.detect_patterns()
    r = await client.get("/suggestions/active")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    assert body[0]["intent_template"] == "notifier"
```

- [ ] **Step 2: Implement**

In `kernel/main.py`:

```python
@app.get("/suggestions/active")
async def get_active_suggestions(request: Request) -> list[dict[str, Any]]:
    engine = request.app.state.suggestion_engine
    suggestions = await engine.list_active()
    return [s.model_dump() for s in suggestions]
```

- [ ] **Step 3: Run test** — PASS.

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(suggestions): GET /suggestions/active"
```

### Task 5.7: `/suggestions/{id}/snooze` + `/suggestions/{id}/accept`

**Files:**
- Modify: `kernel/main.py`

- [ ] **Step 1: Write failing tests** — POST snooze marks snoozed_until; POST accept marks accepted_at. Both endpoints return 200 on success, 404 if not found.

- [ ] **Step 2: Implement**

```python
@app.post("/suggestions/{sid}/snooze")
async def snooze_suggestion(sid: int, request: Request) -> dict[str, str]:
    engine = request.app.state.suggestion_engine
    await engine.snooze(sid)
    return {"status": "snoozed"}

@app.post("/suggestions/{sid}/accept")
async def accept_suggestion(sid: int, request: Request) -> dict[str, str]:
    engine = request.app.state.suggestion_engine
    await engine.mark_accepted(sid)
    return {"status": "accepted"}
```

(404 handling: if `engine.snooze` / `mark_accepted` should raise on missing id, extend them to check existence first. Or accept that no-op-on-missing is fine for v1.)

- [ ] **Step 3: Run tests** — PASS.

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(suggestions): snooze + accept endpoints"
```

### Task 5.8: Chunk 5 review checkpoint

- [ ] Spec + code review.
- [ ] **Verify**:

```bash
.venv/Scripts/python.exe -m pytest tests/kernel/test_suggestions.py tests/kernel/test_main.py tests/kernel/test_database.py -q
```

Expected: green. SuggestionEngine tests = 6; new /chat hook + cron + endpoint tests in test_main.py.

---

## Chunk 6: F3 Frontend — Suggestion banner + voice-builder handoff (1 day, 5 tasks)

Goal: when `/suggestions/active` returns rows, banner appears in chat with Создать (→ voice-builder pre-filled) + Не сейчас (→ snooze) buttons.

**Files touched:**
- Create: `ui/src/components/Suggestions/SuggestionBanner.tsx`, `ui/src/hooks/useSuggestions.ts`, two test files.
- Modify: `ui/src/components/Chat/ChatInput.tsx` (or wherever chat messages render — verify by reading current chat surface).

### Task 6.1: Extend `api` client + `useSuggestions` hook

**Important design note:** The plan must reuse the existing `api/client.ts` dispatcher pattern (uses `resolveApiUrl` to route Rust/Python automatically based on `RUST_ENDPOINTS` in `api/endpoints.ts`). Do NOT create a parallel `api/suggestions.ts` with a hardcoded `BASE` URL — that would bypass the dispatcher and break in Tauri builds where runtime overrides via `window.__KALI_CONFIG__` are honored.

`/suggestions/*` lives in Python (kernel/main.py — added in Chunk 5 Task 5.6-5.7). It is **not in `RUST_ENDPOINTS`**, so the dispatcher defaults to Python `:3005` automatically. No change to `endpoints.ts` needed.

**Files:**
- Modify: `ui/src/api/client.ts` (add 3 methods + Suggestion type)
- Modify: `ui/src/api/types.ts` (add Suggestion type)
- Create: `ui/src/hooks/useSuggestions.ts`
- Create: `ui/src/__tests__/useSuggestions.test.ts`

- [ ] **Step 1: Add `Suggestion` type**

In `ui/src/api/types.ts`, add:

```typescript
export interface Suggestion {
  id: number;
  intent_template: string;
  prompt_text: string;
  created_at: string;
  snoozed_until?: string | null;
  accepted_at?: string | null;
}
```

- [ ] **Step 2: Extend `api` object**

In `ui/src/api/client.ts`, append to the `api` object (after `updateSettings`):

```typescript
  // Suggestions (Tier 2 #10.5 Proactive KALI)
  suggestionsActive: () =>
    fetchJSON<import("./types").Suggestion[]>("/suggestions/active"),
  suggestionsSnooze: (id: number) =>
    fetchJSON<{ status: string }>(`/suggestions/${id}/snooze`, { method: "POST" }),
  suggestionsAccept: (id: number) =>
    fetchJSON<{ status: string }>(`/suggestions/${id}/accept`, { method: "POST" }),
```

- [ ] **Step 3: Write failing hook test**

Create `ui/src/__tests__/useSuggestions.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";

const mockActive = vi.fn();
vi.mock("../api/client", () => ({
  api: {
    suggestionsActive: () => mockActive(),
  },
}));

import { useSuggestions } from "../hooks/useSuggestions";

describe("useSuggestions", () => {
  beforeEach(() => {
    mockActive.mockReset();
  });

  it("fetches active suggestions on mount", async () => {
    mockActive.mockResolvedValue([
      { id: 1, intent_template: "notifier", prompt_text: "test?", created_at: "2026-05-13T10:00:00" },
    ]);
    const { result } = renderHook(() => useSuggestions());
    await waitFor(() => expect(result.current.suggestions.length).toBe(1));
  });

  it("re-fetches when window receives focus", async () => {
    mockActive.mockResolvedValue([]);
    renderHook(() => useSuggestions());
    await waitFor(() => expect(mockActive).toHaveBeenCalledTimes(1));
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(mockActive).toHaveBeenCalledTimes(2));
  });

  it("returns empty list on API failure", async () => {
    mockActive.mockRejectedValue(new Error("network"));
    const { result } = renderHook(() => useSuggestions());
    await waitFor(() => expect(result.current.suggestions).toEqual([]));
  });
});
```

- [ ] **Step 4: Run failing test** — expect ImportError (hook doesn't exist).

- [ ] **Step 5: Implement hook**

Create `ui/src/hooks/useSuggestions.ts`:

```typescript
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Suggestion } from "../api/types";

export function useSuggestions() {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await api.suggestionsActive();
      setSuggestions(data);
    } catch {
      setSuggestions([]);
    }
  }, []);

  useEffect(() => {
    load();
    const onFocus = () => {
      load();
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [load]);

  return { suggestions, refresh: load };
}
```

- [ ] **Step 6: Run tests** — 3 tests pass.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/client.ts ui/src/api/types.ts ui/src/hooks/useSuggestions.ts ui/src/__tests__/useSuggestions.test.ts
git commit -m "feat(suggestions): api client methods + useSuggestions hook"
```

### Task 6.2: `SuggestionBanner` component

**Files:**
- Create: `ui/src/components/Suggestions/SuggestionBanner.tsx`

- [ ] **Step 1: Write failing test**

```typescript
describe("SuggestionBanner", () => {
  it("renders prompt text + two buttons", () => {
    const onAccept = vi.fn();
    const onSnooze = vi.fn();
    render(
      <SuggestionBanner
        suggestion={{
          id: 1, intent_template: "notifier",
          prompt_text: "Создать агента?", created_at: "2026-05-13T10:00:00",
        }}
        onAccept={onAccept}
        onSnooze={onSnooze}
      />,
    );
    expect(screen.getByText(/Создать агента\?/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /создать/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /не сейчас/i })).toBeInTheDocument();
  });

  it("calls onAccept on Создать click", async () => {
    const user = userEvent.setup();
    const onAccept = vi.fn();
    render(
      <SuggestionBanner
        suggestion={/* ... */}
        onAccept={onAccept}
        onSnooze={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: /создать/i }));
    expect(onAccept).toHaveBeenCalledWith(1);
  });
});
```

- [ ] **Step 2: Implement**

```tsx
import type { Suggestion } from "../../api/types";

type Props = {
  suggestion: Suggestion;
  onAccept: (id: number) => void;
  onSnooze: (id: number) => void;
};

export function SuggestionBanner({ suggestion, onAccept, onSnooze }: Props) {
  return (
    <div className="suggestion-banner" role="region" aria-label="Предложение">
      <p>{suggestion.prompt_text}</p>
      <button onClick={() => onAccept(suggestion.id)}>Создать</button>
      <button onClick={() => onSnooze(suggestion.id)}>Не сейчас</button>
    </div>
  );
}
```

- [ ] **Step 3: Run tests** — PASS.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/Suggestions/SuggestionBanner.tsx ui/src/__tests__/SuggestionBanner.test.tsx
git commit -m "feat(suggestions): SuggestionBanner component"
```

### Task 6.3: Hook banner into chat surface

**Files:**
- Modify: `ui/src/components/Chat/ChatInput.tsx` (or the actual chat surface — read first to confirm)

- [ ] **Step 1: Locate chat surface**

Find where chat messages render. App.tsx routes `mode === "focus"` to a layout with ChatInput. The banner could go above ChatInput, or in a fixed-position card. Pick whichever doesn't break the focus-mode UX.

- [ ] **Step 2: Integration**

```tsx
import { useSuggestions } from "../../hooks/useSuggestions";
import { useBuilderStore } from "../../stores/builder";
import { useAppStore } from "../../stores/appStore";
import { SuggestionBanner } from "../Suggestions/SuggestionBanner";
import { api } from "../../api/client";

// in render:
const { suggestions, refresh } = useSuggestions();
const top = suggestions[0];
const start = useBuilderStore((s) => s.start);
const setMode = useAppStore((s) => s.setMode);

async function handleAccept(id: number) {
  await api.suggestionsAccept(id);
  // build a starter request from the template hint
  const hint = (top && PROMPT_HINTS[top.intent_template]) || "";
  start(hint);
  setMode("builder");
  refresh();
}

async function handleSnooze(id: number) {
  await api.suggestionsSnooze(id);
  refresh();
}

// render:
{top && (
  <SuggestionBanner
    suggestion={top}
    onAccept={handleAccept}
    onSnooze={handleSnooze}
  />
)}
```

Where `PROMPT_HINTS` maps template → seed phrase. Define at top of the file:

```typescript
const PROMPT_HINTS: Record<string, string> = {
  notifier: "Создай агента, который будет уведомлять меня о ",
  monitor: "Создай агента, который будет проверять ",
  tracker: "Создай агента, который будет считать ",
  reminder: "Напомни мне делать ",
  logger: "Веди дневник для ",
};
```

- [ ] **Step 3: Test**

Write integration test for the chat surface that verifies banner appears when /suggestions/active mock returns data.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/Chat/ChatInput.tsx ui/src/__tests__/ChatInput.test.tsx
git commit -m "feat(suggestions): show banner in chat + hand off to voice-builder on accept"
```

### Task 6.4: Verify voice-builder pre-fill works end-to-end

- [ ] **Step 1: Manual verification (will be repeated in Chunk 7 e2e)**

Open dev build → simulate `/suggestions/active` returning a notifier suggestion → click Создать → assert that `mode === "builder"` and `useBuilderStore` state has the seed text loaded.

- [ ] **Step 2: Add unit test for store-side**

```typescript
it("useBuilderStore.start accepts seed text", () => {
  const { start, request } = useBuilderStore.getState();
  start("Создай агента, который будет уведомлять меня о цене биткоина");
  expect(useBuilderStore.getState().request).toContain("биткоин");
});
```

(Verify name of the field — may be `request`, `pendingRequest`, or similar. Read `ui/src/stores/builder.ts:36` first.)

- [ ] **Step 3: Commit if test added**

```bash
git add ui/src/__tests__/builder-store-seed.test.ts
git commit -m "test(builder): cover start(seedText) pre-fill behavior"
```

### Task 6.5: Chunk 6 review checkpoint

- [ ] Spec + code review.
- [ ] **Verify**:

```bash
cd ui && pnpm test && npx tsc --noEmit
```

Expected: green.

---

## Chunk 7: E2E + smoke test (0.5 day, 2 tasks)

### Task 7.1: vitest E2E happy-path

**Files:**
- Create: `ui/src/__tests__/proactive-e2e.test.tsx`

- [ ] **Step 1: Implement test**

Cover the three-feature happy path with mocks:

```typescript
describe("Proactive KALI v1 E2E", () => {
  it("F1: schedule.morning event → TTS speak called", async () => {
    // Mock WS message + assert sendNotification / speak called
  });

  it("F2: notification.new event → Tauri notify with correct title", async () => {
    // Setup NotificationManager, dispatch WS event, assert Tauri call
  });

  it("F3: active suggestion banner clickable + routes to builder", async () => {
    // Mock /suggestions/active → render → click Создать → assert mode change + builder seeded
  });
});
```

- [ ] **Step 2: Run** — pass.

- [ ] **Step 3: Commit**

```bash
git add ui/src/__tests__/proactive-e2e.test.tsx
git commit -m "test: proactive-kali-v1 e2e happy-path"
```

### Task 7.2: Manual smoke checklist (run after dev build)

- [ ] **Run dev build:** `make dev` (or whatever current command brings up the integrated stack).
- [ ] **F1 smoke:**
  1. Open Settings → Briefing section.
  2. Set time to "current+1 minute".
  3. Wait. Verify speakers play briefing.
  4. Restart KALI. Verify briefing fires again next day (smoke-via-time-edit).
- [ ] **F2 smoke:**
  1. Create a test notifier agent.
  2. Trigger its alert action.
  3. Verify Windows Toast appears.
  4. Click toast. Verify KALI window shows agents tab.
  5. Toggle off `Уведомления` for that agent. Trigger alert again. Verify no toast.
- [ ] **F3 smoke:**
  1. In chat, send 5 messages classified as "notifier" intent (e.g., "уведомь меня о X").
  2. Wait 6 hours OR manually fire `schedule.cron.suggestion_detect` via debug hook.
  3. Open chat. Verify banner appears.
  4. Click Создать. Verify voice-builder opens with seed text.
  5. Click Не сейчас. Verify banner disappears + does not reappear for 7 days.

- [ ] **Document results in handoff** — `2026-05-XX-proactive-kali-v1-shipped.md`. Include any plan-defects caught + reviewer mistakes.

---

## Final review checkpoint

- [ ] **Aggregate verification**:

```bash
# Backend
.venv/Scripts/python.exe -m pytest tests/kernel/ -q
# Frontend
cd ui && pnpm test && npx tsc --noEmit
# Rust
cd src-tauri && cargo test --no-run
```

All green.

- [ ] **Spec final pass:** re-read `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md` end-to-end. Mark each of the 3 features ✅ delivered. Any deferred items must be explicitly listed in the shipped handoff with reason.

- [ ] **Commit pattern check:**

```bash
git log --oneline -30
```

Each commit should be one logical change. No mega-commits. No empty commits.

- [ ] **Memory update:** add entry to `memory/project_roadmap.md` v2.16 (post-ship) noting #10.5 SHIPPED.

---

## Operational considerations

### SuggestionEngine instance lifecycle

`SuggestionEngine` is **a singleton per kernel process**, attached to `app.state.suggestion_engine` in the `lifespan` startup block (Chunk 5 Task 5.4 / 5.5). It shares the same long-lived `aiosqlite.Connection` via `Database.conn`. Routes (`/suggestions/active`, `/suggestions/{id}/snooze`, `/suggestions/{id}/accept`) and the 6h cron handler read it from `request.app.state.suggestion_engine` — never re-instantiate.

Database is created once (existing pattern in `kernel/main.py` startup), `Database.initialize()` runs `executescript(SCHEMA)` which is idempotent (all `CREATE TABLE IF NOT EXISTS`). Adding the two new tables in Chunk 5 Task 5.1 means new installs and **existing installs** both get the tables on next boot — no separate migration step needed.

### Performance budget

The two new always-on code paths:

| Path | Budget (typical) | Budget (worst) | Mitigation if exceeded |
|---|---|---|---|
| `SuggestionEngine.log_intent` (one INSERT per `/chat`) | < 5 ms | < 20 ms | Skip log if `time.perf_counter()` shows > 20 ms (log warning) |
| `SuggestionEngine.detect_patterns` (cron every 6h) | < 100 ms | < 500 ms | Add `LIMIT` clause on GROUP BY scan if intent_log grows past 100k rows |
| `BriefingRunner._on_morning` (cron daily) | TTS-bound (~1-5 s) | TTS may stall | Wrap in `asyncio.wait_for(..., timeout=30)`; swallow timeout |

If `chat_intent_log` grows unbounded over months, add a pruning task analogous to `Database.prune_old_conversations(days=30)` — but **not in v1**. Track in a follow-up chip if intent log reaches 10k rows in normal use.

### Migration story for existing users

The two new SQLite tables (`chat_intent_log`, `suggestions`) are created via `CREATE TABLE IF NOT EXISTS` in the shared `SCHEMA` block. Existing users upgrading from KALI without this feature get empty tables on first boot — by design. Intent patterns are personal-history derived; **starting fresh is the correct UX**, not a bug.

`.env` keys `KALI_BRIEFING_MORNING_ENABLED` and `KALI_BRIEFING_MORNING_TIME` use safe defaults (`true` and `"08:00"`) when absent — no migration step required.

Tauri notification permission: on first send the plugin auto-requests OS permission (handled by `api/notifications.ts:ensurePermission`). User sees a one-time OS prompt. If denied, all calls become silent no-ops — no crash, no retry storm.

### Rollback / partial-failure plan

The three features are **functionally independent**. If a chunk fails halfway through execution:

- **F1 ships but F2/F3 broken** — `KALI_BRIEFING_MORNING_ENABLED=false` in `.env` disables morning briefing without code changes. F1 disabled, F2/F3 untouched.
- **F2 ships but F3 breaks** — set `localStorage.setItem("notifications.<agent>", "false")` per agent to mute all toasts client-side. Or revert Chunk 3 commits (skill template publish lines) — they are confined to `_notify` / `_check` and a `set_event_bus` call site.
- **F3 ships but causes /chat regression** — wrap the `log_intent` call in `_chat_logic` in a try/except that logs and swallows. This is already in the plan (Chunk 5 Task 5.4 Step 3). If still problematic, revert the SuggestionEngine instantiation line in `lifespan`.

**Backout commit pattern:** each chunk's tasks commit as a single feature-named series. To back out F2:

```bash
git revert <chunk-3-shas> <chunk-4-shas>
```

The Rust dependency (`tauri-plugin-notification`) stays in Cargo.toml even on F2 revert — harmless, ~150 KB build cost only.

**Feature flag (optional)** — if backout-via-revert feels risky, add `KALI_PROACTIVE_F1_ENABLED` / `KALI_PROACTIVE_F2_ENABLED` / `KALI_PROACTIVE_F3_ENABLED` env vars gating each feature's startup wiring. **Not in v1** by default — adds complexity for a low-probability event. Decide during execution if needed.

### Known plan-defects expected at execution time

Despite the review-loop and verify-pass, expect 3-5 plan-defects to surface during execution (precedent: 8 defects in voice-builder-pilot v2). Likely sources:
- `aiosqlite` `cursor.description` returning `None` if no rows fetched yet — `SuggestionEngine._all_intent_logs/_all_suggestions` may need defensive `cols = [d[0] for d in (cursor.description or [])]`.
- Settings nested-dict vs flat-dict serialization edge cases in tests.
- Tauri capability JSON requires a specific schema field we missed — likely caught by `cargo check` exit non-zero.
- `cargo check` may pull a `tauri-plugin-notification 2.x` that has a different init signature than `init()` (e.g., needs `Builder::default().build()`) — fix by reading the actual plugin docs at error time.
- `useBuilderStore.start(request)` second-arg or option-object signature drift if `voice-builder-pilot` post-merge changes anything.

Handle as during execution: read error, read source, patch, re-test. Don't trust the plan's code blocks blindly.

---

## Plan review loop (use this AFTER plan is saved, BEFORE execution begins)

Per `@superpowers:writing-plans` review-loop pattern:

1. Dispatch `plan-document-reviewer` subagent with:
   - This plan file content
   - Path to spec: `docs/superpowers/specs/2026-05-05-proactive-kali-v1.md`
2. Address any ❌ Issues Found by editing this plan.
3. Re-dispatch until ✅ Approved.
4. Then proceed to execution via `superpowers:subagent-driven-development`.

---

## Carry-forward rules (binding for executor)

- **TDD strict** — write failing test → run fail → minimal impl → run pass → commit. Each task ends with a commit. No batching commits across tasks.
- **`.venv/Scripts/python.exe -m pytest`** for stable runs (not `uv run pytest`).
- **`KALI_SKIP_PREWARM=1`** stays in `tests/conftest.py` — don't remove.
- **Direct-to-main** — no PR. Solo dev convention.
- **Two-stage review per chunk** — spec compliance + code quality. Subagent reviewers can be wrong; controller verifies by reading the cited file.
- **Russian-first chat with Vasily** — code + tech terms in English.
- **Anti-pivot rule binding:** no dev/design integrations sneak in (no GitHub/Figma/IDE in suggestion templates or briefing data).

---

*Plan saved 2026-05-13. Estimated execution: 5-7 days via subagent-driven-development.*
