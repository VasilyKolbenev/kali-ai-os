# Voice Builder Pilot — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Доказать core promise KALI — non-tech user говорит идею → через ≤60 сек получает рабочего агента, с possibility отменить/переделать голосом и превью до запуска.

**Architecture:** Тонкий flow-orchestrator на бэке связывает уже существующие компоненты (`intent_classifier`, `wizard`, `skill_generator`, `safety_gate`, `deployer`) в единый stateful pipeline. In-memory session store хранит wizard state между HTTP запросами. Voice pipeline (`kernel/voice/pipeline.py`) ловит "создай агента" в transcribed text и передаёт управление builder-flow. React UI показывает прогресс и превью, но HTTP/voice работает и без него.

**Tech Stack:** Python 3.12 + FastAPI (существующий), pytest + pytest-asyncio, existing `tts_router` + STT + pipeline; React 19 + TypeScript + Zustand (существующий UI stack).

**Success criteria:**
1. Automated test `test_builder_e2e_voice.py` проходит: simulated voice input → deployed skill → test invocation → PASS за ≤60s wall clock
2. End-to-end demo video: реальный human голосом создает "напоминалку пить воду" за ≤60s без склеек
3. Rollback tested: "нет, переделай" корректно сбрасывает state
4. Preview shown: user слышит+видит описание ДО deploy

**Non-goals (out of scope для pilot):**
- Агенты с кастомным Python-кодом через LLM (agent_generator) — только skill templates
- Templates library / gallery / remix (future Tier 2)
- Share-to-reels / UGC loop (future Tier 2)
- Mobile версия (отдельная платформа)
- UI redesign за пределами Builder panel
- Локализация (только RU; английский — если тривиально, иначе позже)

---

## Chunk 1: Session Store + Flow Orchestrator

**Why first:** Session store — это state backbone. Flow orchestrator зависит от него. Эти два модуля покроют 80% business logic и enable всё остальное (HTTP, voice, UI).

### Task 1: SessionStore — in-memory wizard state registry

**Files:**
- Create: `kernel/builder/session_store.py`
- Test: `tests/kernel/builder/test_session_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kernel/builder/test_session_store.py
import pytest
from kernel.builder.session_store import SessionStore, SessionNotFound


def test_create_and_get_session() -> None:
    store = SessionStore()
    sid = store.create(request="Напомни пить воду", intent_type="skill", template="reminder")
    session = store.get(sid)
    assert session.request == "Напомни пить воду"
    assert session.intent_type == "skill"
    assert session.template == "reminder"


def test_get_unknown_raises() -> None:
    store = SessionStore()
    with pytest.raises(SessionNotFound):
        store.get("nonexistent")


def test_delete_session() -> None:
    store = SessionStore()
    sid = store.create(request="x", intent_type="skill", template=None)
    store.delete(sid)
    with pytest.raises(SessionNotFound):
        store.get(sid)


def test_ttl_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sessions older than TTL are evicted on access."""
    import time
    now = [1000.0]
    monkeypatch.setattr("kernel.builder.session_store.time.monotonic", lambda: now[0])

    store = SessionStore(ttl_seconds=60)
    sid = store.create(request="x", intent_type="skill", template=None)
    now[0] = 1061.0  # advance past TTL
    with pytest.raises(SessionNotFound):
        store.get(sid)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd C:/Users/User/Desktop/Jarvis
uv run --with pytest --with pytest-asyncio pytest tests/kernel/builder/test_session_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'kernel.builder.session_store'`.

- [ ] **Step 3: Implement session_store.py**

```python
# kernel/builder/session_store.py
"""In-memory session registry for multi-turn wizard flows."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class SessionNotFound(KeyError):
    """Raised when a session_id is unknown or expired."""


@dataclass
class BuilderSession:
    """Tracks state of one builder flow from request → deploy."""

    session_id: str
    request: str
    intent_type: str  # "skill" | "agent"
    template: str | None
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    step: int = 0
    spec: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.monotonic)

    @property
    def is_complete(self) -> bool:
        return self.step >= len(self.questions)

    @property
    def current_question(self) -> str | None:
        if self.step < len(self.questions):
            return self.questions[self.step]
        return None


class SessionStore:
    """Thread-local in-memory session store with TTL cleanup."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._sessions: dict[str, BuilderSession] = {}
        self._ttl = ttl_seconds

    def create(
        self,
        request: str,
        intent_type: str,
        template: str | None,
    ) -> str:
        sid = uuid.uuid4().hex[:12]
        self._sessions[sid] = BuilderSession(
            session_id=sid,
            request=request,
            intent_type=intent_type,
            template=template,
        )
        return sid

    def get(self, session_id: str) -> BuilderSession:
        self._evict_expired()
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        return self._sessions[session_id]

    def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        now = time.monotonic()
        stale = [sid for sid, s in self._sessions.items() if now - s.created_at > self._ttl]
        for sid in stale:
            del self._sessions[sid]
            logger.debug("Evicted expired builder session: %s", sid)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/builder/test_session_store.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/session_store.py tests/kernel/builder/
git commit -m "feat(builder): add SessionStore for multi-turn wizard state"
```

---

### Task 2: BuilderFlow — orchestrator connecting intent → wizard → preview → deploy

**Files:**
- Create: `kernel/builder/flow.py`
- Test: `tests/kernel/builder/test_flow.py`

- [ ] **Step 1: Write the failing test** (focus on state transitions, not LLM calls — mock intent)

```python
# tests/kernel/builder/test_flow.py
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from kernel.builder.flow import BuilderFlow
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import SessionStore


def _mock_intent(type_: str = "skill", template: str = "reminder") -> IntentResult:
    return IntentResult(type=type_, template=template, confidence=0.9, reason="mocked")


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BuilderFlow:
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: _mock_intent(),
    )
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    return BuilderFlow(
        session_store=SessionStore(),
        agents_dir=tmp_path / "agents",
        skill_executor=executor,
        scheduler=None,
    )


async def test_start_returns_first_question(flow: BuilderFlow) -> None:
    result = flow.start("Напомни пить воду каждые 2 часа")
    assert result["session_id"]
    assert result["question"]  # wizard generated ≥1 question
    assert result["total_steps"] >= 1


async def test_answer_progresses_until_complete(flow: BuilderFlow) -> None:
    start = flow.start("Напомни пить воду")
    sid = start["session_id"]

    # Feed answers until wizard completes
    total = start["total_steps"]
    for i in range(total):
        result = flow.answer(sid, f"ответ-{i}")
        if result["done"]:
            assert i == total - 1
            assert result["preview"]["name"]
            return
    pytest.fail("Wizard didn't complete after all answers")


async def test_deploy_creates_skill(flow: BuilderFlow) -> None:
    start = flow.start("Напомни пить воду")
    sid = start["session_id"]
    for _ in range(start["total_steps"]):
        flow.answer(sid, "каждые 2 часа")
    result = await flow.deploy(sid)
    assert result["status"] == "deployed"


async def test_cancel_removes_session(flow: BuilderFlow) -> None:
    start = flow.start("Напомни")
    sid = start["session_id"]
    flow.cancel(sid)
    with pytest.raises(Exception):
        flow.answer(sid, "x")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/builder/test_flow.py -v
```

Expected: `ModuleNotFoundError: No module named 'kernel.builder.flow'`.

- [ ] **Step 3: Implement flow.py**

```python
# kernel/builder/flow.py
"""Builder flow — orchestrates intent → wizard → preview → deploy with a single entrypoint per phase."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kernel.builder.deployer import deploy_skill
from kernel.builder.intent_classifier import classify_intent
from kernel.builder.session_store import BuilderSession, SessionStore
from kernel.builder.skill_generator import generate_skill
from kernel.builder.wizard import create_wizard

logger = logging.getLogger(__name__)


class BuilderFlow:
    """High-level orchestrator tying together existing builder modules."""

    def __init__(
        self,
        session_store: SessionStore,
        agents_dir: Path,
        skill_executor: Any,
        scheduler: Any | None = None,
    ) -> None:
        self._store = session_store
        self._agents_dir = agents_dir
        self._executor = skill_executor
        self._scheduler = scheduler

    def start(self, request: str) -> dict[str, Any]:
        """Phase 1: classify intent, create wizard session, return first question."""
        intent = classify_intent(request)
        if intent.type != "skill":
            # Pilot scope: skills only. Agent generation deferred.
            raise ValueError(
                f"Agent generation out of pilot scope (got intent: {intent.type}). "
                "Pilot supports skill templates only."
            )

        wizard = create_wizard(request, intent)
        sid = self._store.create(
            request=request,
            intent_type=intent.type,
            template=intent.template,
        )
        session = self._store.get(sid)
        session.questions = wizard.questions

        return {
            "session_id": sid,
            "question": session.current_question,
            "total_steps": len(session.questions),
            "template": intent.template,
        }

    def answer(self, session_id: str, text: str) -> dict[str, Any]:
        """Phase 2: record answer, return next question OR preview if done."""
        session = self._store.get(session_id)
        session.answers.append(text)
        session.step += 1

        if not session.is_complete:
            return {
                "done": False,
                "question": session.current_question,
                "step": session.step,
                "total_steps": len(session.questions),
            }

        # Build spec for preview
        spec = self._build_spec(session)
        session.spec = spec
        return {
            "done": True,
            "preview": spec,
        }

    async def deploy(self, session_id: str) -> dict[str, Any]:
        """Phase 3: materialise skill + deploy + clean up session."""
        session = self._store.get(session_id)
        if session.spec is None:
            raise ValueError("Cannot deploy: wizard not complete")

        skill_dir = generate_skill(
            name=session.spec["name"],
            template=session.spec["template"],
            description=session.spec["description"],
            config=session.spec["config"],
            agents_dir=self._agents_dir,
        )

        result = await deploy_skill(
            skill_dir=skill_dir,
            skill_executor=self._executor,
            scheduler=self._scheduler,
        )
        self._store.delete(session_id)
        return result

    def cancel(self, session_id: str) -> None:
        """Phase 4: reset session without deploying."""
        self._store.delete(session_id)

    def _build_spec(self, session: BuilderSession) -> dict[str, Any]:
        """Materialise a skill spec from session answers (mirrors WizardSession.build_spec)."""
        import re

        name = re.sub(r"[^\w\s-]", "", session.request.lower()).strip()
        name = re.sub(r"[\s_]+", "-", name)[:40].strip("-")
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(session.questions, session.answers)):
            if "часто" in q or "interval" in q.lower():
                config["interval"] = a
            elif "цел" in q or "goal" in q.lower():
                config["goal"] = a
            elif "уведом" in q or "куда" in q:
                config["notify_channel"] = a
            else:
                config[f"param_{i}"] = a
        return {
            "name": name,
            "description": session.request,
            "type": session.intent_type,
            "template": session.template,
            "config": config,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/builder/test_flow.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/flow.py tests/kernel/builder/test_flow.py
git commit -m "feat(builder): add BuilderFlow orchestrator (intent → wizard → preview → deploy)"
```

---

## Chunk 2: HTTP Endpoints

**Why:** Exposes BuilderFlow to any client (voice pipeline, UI, external tools). Keep endpoints thin — all logic lives in `BuilderFlow`.

### Task 3: Wire BuilderFlow into FastAPI app state

**Files:**
- Modify: `kernel/main.py` (near app.state initialization)
- Test: `tests/kernel/test_main.py` (add fixture + smoke test)

- [ ] **Step 1: Read current `app.state` setup location**

Run: `grep -n "app.state" kernel/main.py | head -10`

Note: find where `config_manager`, `agent_runtime`, `skill_executor` are attached — add `builder_flow` there.

- [ ] **Step 2: Modify kernel/main.py — add BuilderFlow initialization**

Locate the section where `skill_executor` and `scheduler` are assigned to `app.state` (grep for `app.state.skill_executor`). Add right after:

```python
from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore

app.state.builder_flow = BuilderFlow(
    session_store=SessionStore(),
    agents_dir=Path("agents"),
    skill_executor=app.state.skill_executor,
    scheduler=getattr(app.state, "scheduler", None),
)
```

- [ ] **Step 3: Smoke test — import still works**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_main.py -v
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py
git commit -m "feat(builder): expose BuilderFlow on FastAPI app state"
```

---

### Task 4: POST /builder/start endpoint

**Files:**
- Modify: `kernel/main.py` (add new endpoint block)
- Test: `tests/kernel/test_builder_endpoints.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kernel/test_builder_endpoints.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore
from kernel.main import create_app


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: type("I", (), {"type": "skill", "template": "reminder", "confidence": 0.9, "reason": "mock"}),
    )
    app = create_app()
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    app.state.builder_flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=tmp_path / "agents",
        skill_executor=executor,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_start_returns_session(client):
    r = await client.post("/builder/start", json={"request": "Напомни пить воду каждые 2 часа"})
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"]
    assert data["question"]
    assert data["total_steps"] >= 1


async def test_start_rejects_empty_request(client):
    r = await client.post("/builder/start", json={"request": ""})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_builder_endpoints.py::test_start_returns_session -v
```

Expected: 404 (endpoint doesn't exist).

- [ ] **Step 3: Implement /builder/start in kernel/main.py**

Find the section that defines endpoints (search for `@app.post("/tts")` as anchor). Add below TTS endpoints:

```python
@app.post("/builder/start")
async def builder_start(request: Request) -> dict[str, Any]:
    """Start a builder flow from a natural-language request."""
    from fastapi.responses import JSONResponse

    body = await request.json()
    text = (body.get("request") or "").strip()
    if not text:
        return JSONResponse({"error": "request must be non-empty"}, status_code=400)

    try:
        result = request.app.state.builder_flow.start(text)
        return result
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("builder/start failed")
        return JSONResponse({"error": str(e)}, status_code=500)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_builder_endpoints.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_builder_endpoints.py
git commit -m "feat(builder): POST /builder/start endpoint"
```

---

### Task 5: POST /builder/answer + /builder/deploy + /builder/cancel endpoints

**Files:**
- Modify: `kernel/main.py`
- Test: `tests/kernel/test_builder_endpoints.py` (append)

- [ ] **Step 1: Write failing tests (end-to-end happy path + cancel)**

```python
# append to tests/kernel/test_builder_endpoints.py

async def test_full_happy_path(client):
    r = await client.post("/builder/start", json={"request": "Напомни пить воду"})
    sid = r.json()["session_id"]
    total = r.json()["total_steps"]

    for i in range(total):
        r = await client.post("/builder/answer", json={"session_id": sid, "answer": f"ответ-{i}"})
        data = r.json()
        if data["done"]:
            assert data["preview"]["name"]
            break

    r = await client.post("/builder/deploy", json={"session_id": sid})
    assert r.status_code == 200
    assert r.json()["status"] == "deployed"


async def test_cancel_mid_flow(client):
    r = await client.post("/builder/start", json={"request": "Напомни"})
    sid = r.json()["session_id"]

    r = await client.post("/builder/cancel", json={"session_id": sid})
    assert r.status_code == 200

    # Subsequent answer on cancelled session should 404
    r = await client.post("/builder/answer", json={"session_id": sid, "answer": "x"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_builder_endpoints.py -v
```

Expected: 404 on /builder/answer.

- [ ] **Step 3: Implement remaining endpoints in kernel/main.py**

Add after `/builder/start`:

```python
@app.post("/builder/answer")
async def builder_answer(request: Request) -> dict[str, Any]:
    from fastapi.responses import JSONResponse
    from kernel.builder.session_store import SessionNotFound

    body = await request.json()
    sid = body.get("session_id", "")
    text = (body.get("answer") or "").strip()
    if not sid or not text:
        return JSONResponse({"error": "session_id and answer required"}, status_code=400)

    try:
        return request.app.state.builder_flow.answer(sid, text)
    except SessionNotFound:
        return JSONResponse({"error": "session not found or expired"}, status_code=404)


@app.post("/builder/deploy")
async def builder_deploy(request: Request) -> dict[str, Any]:
    from fastapi.responses import JSONResponse
    from kernel.builder.session_store import SessionNotFound

    body = await request.json()
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    try:
        return await request.app.state.builder_flow.deploy(sid)
    except SessionNotFound:
        return JSONResponse({"error": "session not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/builder/cancel")
async def builder_cancel(request: Request) -> dict[str, Any]:
    from fastapi.responses import JSONResponse

    body = await request.json()
    sid = body.get("session_id", "")
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)

    request.app.state.builder_flow.cancel(sid)
    return {"status": "cancelled"}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_builder_endpoints.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_builder_endpoints.py
git commit -m "feat(builder): POST /builder/{answer,deploy,cancel} endpoints"
```

---

## Chunk 3: Voice Pipeline Integration

**Why:** Connects the existing voice loop to BuilderFlow so the user can speak rather than type.

### Task 6: Intent detection in VoicePipeline — start builder on "создай агента"

**Files:**
- Modify: `kernel/voice/pipeline.py` (extend `_handle_transcription`)
- Test: `tests/kernel/test_pipeline_builder_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kernel/test_pipeline_builder_integration.py
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kernel.voice.pipeline import _detect_builder_trigger


@pytest.mark.parametrize("text,expected", [
    ("Создай агента чтобы напоминал пить воду", True),
    ("Сделай агента для отслеживания курса биткоина", True),
    ("Сделай скилл напоминалку", True),
    ("Создай скилл для дневника настроения", True),
    ("Какая погода?", False),
    ("Открой калькулятор", False),
    ("", False),
])
def test_detect_builder_trigger(text: str, expected: bool) -> None:
    assert _detect_builder_trigger(text) == expected
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_pipeline_builder_integration.py -v
```

Expected: `ImportError: cannot import name '_detect_builder_trigger'`.

- [ ] **Step 3: Add trigger detector + invoke builder in kernel/voice/pipeline.py**

Add at module level (near top, after imports):

```python
_BUILDER_TRIGGER_PATTERNS = [
    r"созда[йи].*агент",
    r"сделай.*агент",
    r"созда[йи].*скилл",
    r"сделай.*скилл",
    r"построй.*агент",
]


def _detect_builder_trigger(text: str) -> bool:
    """Return True if transcribed text starts a builder flow."""
    import re
    if not text:
        return False
    lowered = text.lower().strip()
    return any(re.search(p, lowered) for p in _BUILDER_TRIGGER_PATTERNS)
```

In `_handle_transcription`, before the normal LLM path, add:

```python
# Detect builder intent — divert to BuilderFlow if matched
if _detect_builder_trigger(stt_result.text):
    logger.info("Builder trigger detected: %r", stt_result.text)
    builder_flow = getattr(self._app_state, "builder_flow", None) if hasattr(self, "_app_state") else None
    if builder_flow:
        try:
            result = builder_flow.start(stt_result.text)
            # Speak first question + wait for voice answer (handled by follow-up turn)
            await self._speak(result["question"])
            await self._bus.publish(
                Event(
                    topic="builder.started",
                    source="voice-pipeline",
                    payload={"session_id": result["session_id"], "question": result["question"]},
                )
            )
            return
        except Exception:
            logger.exception("Builder flow start failed — falling back to normal LLM")
```

Note: the `self._app_state` wiring needs a small constructor change to `VoicePipeline` — pass `app_state` so pipeline can reach `builder_flow`. Add a parameter:

```python
def __init__(
    self,
    event_bus: EventBus,
    voice_config: VoiceConfig,
    llm_config: LLMConfig,
    tools: list[dict[str, Any]],
    app_state: Any = None,   # NEW
) -> None:
    ...
    self._app_state = app_state
```

And a `_speak` helper that reuses TTS playback:

```python
async def _speak(self, text: str) -> None:
    try:
        audio, sr = await asyncio.to_thread(tts_router.generate_audio, text)
        if len(audio) > 0:
            await asyncio.to_thread(_play_audio, audio, sr)
    except Exception:
        logger.exception("TTS speak failed")
```

- [ ] **Step 4: Update main.py to pass app_state to VoicePipeline**

```bash
grep -n "VoicePipeline(" kernel/main.py
```

Modify the construction call to add `app_state=app.state`.

- [ ] **Step 5: Run tests**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_pipeline_builder_integration.py tests/kernel/test_pipeline.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/pipeline.py kernel/main.py tests/kernel/test_pipeline_builder_integration.py
git commit -m "feat(voice): detect 'создай агента' in STT and divert to BuilderFlow"
```

---

### Task 7: Multi-turn voice answer handling

**Files:**
- Modify: `kernel/voice/pipeline.py`
- Test: extend `tests/kernel/test_pipeline_builder_integration.py`

- [ ] **Step 1: Add session tracking to pipeline state**

In `VoicePipeline.__init__`, add:
```python
self._active_builder_session: str | None = None
```

- [ ] **Step 2: Route follow-up utterances to /builder/answer when session active**

In `_handle_transcription`, add at the very top:

```python
# Continuation of builder flow — feed answer, speak next question or preview
if self._active_builder_session and self._app_state:
    flow = getattr(self._app_state, "builder_flow", None)
    if flow:
        try:
            result = flow.answer(self._active_builder_session, stt_result.text)
            if result.get("done"):
                preview = result["preview"]
                confirm_text = (
                    f"Я создам {preview['name']}. "
                    f"{preview['description']}. Запускать?"
                )
                await self._speak(confirm_text)
                # Next utterance will be a yes/no — handled in a small state
                self._awaiting_deploy_confirm = True
            else:
                await self._speak(result["question"])
            return
        except Exception:
            logger.exception("Builder answer failed — resetting session")
            self._active_builder_session = None
```

Also after `_detect_builder_trigger` block, save session_id:
```python
self._active_builder_session = result["session_id"]
```

- [ ] **Step 3: Handle deploy confirmation (yes/no)**

Add `self._awaiting_deploy_confirm = False` to `__init__`. In `_handle_transcription`, before builder-answer section:

```python
if self._awaiting_deploy_confirm:
    positive = any(w in stt_result.text.lower() for w in ("да", "запускай", "давай", "ок", "поехали"))
    negative = any(w in stt_result.text.lower() for w in ("нет", "отмени", "переделай"))
    flow = getattr(self._app_state, "builder_flow", None) if self._app_state else None
    if positive and flow and self._active_builder_session:
        result = await flow.deploy(self._active_builder_session)
        await self._speak(f"Готово! Агент {result.get('name', '')} запущен.")
    elif negative and flow and self._active_builder_session:
        flow.cancel(self._active_builder_session)
        await self._speak("Отменил. Попробуем ещё раз?")
    self._awaiting_deploy_confirm = False
    self._active_builder_session = None
    return
```

- [ ] **Step 4: Add test covering the multi-turn flow via mocked BuilderFlow**

```python
# append to tests/kernel/test_pipeline_builder_integration.py
from unittest.mock import MagicMock, AsyncMock


async def test_multi_turn_flow_reaches_deploy(monkeypatch):
    """Simulate: wake word → utterance "создай агента..." → answers → "да" → deploy."""
    from kernel.voice.pipeline import VoicePipeline
    from kernel.models import VoiceConfig, LLMConfig
    from kernel.event_bus import EventBus

    flow = MagicMock()
    flow.start = MagicMock(return_value={
        "session_id": "sid1",
        "question": "Как часто напоминать?",
        "total_steps": 1,
    })
    flow.answer = MagicMock(return_value={
        "done": True,
        "preview": {"name": "water-reminder", "description": "Напоминалка"},
    })
    flow.deploy = AsyncMock(return_value={"status": "deployed", "name": "water-reminder"})

    app_state = MagicMock()
    app_state.builder_flow = flow

    pipe = VoicePipeline(
        event_bus=EventBus(),
        voice_config=VoiceConfig(),
        llm_config=LLMConfig(),
        tools=[],
        app_state=app_state,
    )
    # Stub out TTS playback
    pipe._speak = AsyncMock()

    # Turn 1: builder trigger
    from kernel.voice.stt import STTResult
    await pipe._handle_transcription(STTResult(text="Создай агента для напоминаний", language="ru", confidence=1.0, duration_ms=100))
    assert pipe._active_builder_session == "sid1"

    # Turn 2: answer → done (preview)
    await pipe._handle_transcription(STTResult(text="каждые 2 часа", language="ru", confidence=1.0, duration_ms=100))
    assert pipe._awaiting_deploy_confirm is True

    # Turn 3: "да" → deploy
    await pipe._handle_transcription(STTResult(text="да", language="ru", confidence=1.0, duration_ms=100))
    flow.deploy.assert_awaited_once_with("sid1")
```

- [ ] **Step 5: Run tests**

```bash
uv run --with pytest --with pytest-asyncio pytest tests/kernel/test_pipeline_builder_integration.py -v
```

Expected: 8 passed (7 parametrized + 1 multi-turn).

- [ ] **Step 6: Commit**

```bash
git add kernel/voice/pipeline.py tests/kernel/test_pipeline_builder_integration.py
git commit -m "feat(voice): multi-turn builder flow (answers + yes/no deploy confirm)"
```

---

## Chunk 4: UI Panel

**Why:** Non-tech users need visible progress + preview even with voice. UI = safety net when voice misfires. Minimum: progress + preview + confirm button.

### Task 8: API client for /builder/*

**Files:**
- Create: `ui/src/api/builder.ts`
- Test: `ui/src/api/builder.test.ts` (light)

- [ ] **Step 1: Write the failing test (or skip if no frontend test infra setup — check with lint/typecheck instead)**

```bash
cd ui && ls src/api/*.test.ts 2>/dev/null | head -3
```

If no existing tests — skip test-first for UI, rely on TypeScript + runtime check.

- [ ] **Step 2: Create ui/src/api/builder.ts**

```typescript
// ui/src/api/builder.ts
import { apiUrl } from "./client";

export interface BuilderStartResponse {
  session_id: string;
  question: string;
  total_steps: number;
  template: string | null;
}

export interface BuilderAnswerResponse {
  done: boolean;
  question?: string;
  step?: number;
  total_steps?: number;
  preview?: BuilderPreview;
}

export interface BuilderPreview {
  name: string;
  description: string;
  type: string;
  template: string | null;
  config: Record<string, unknown>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const builderApi = {
  start: (request: string) =>
    postJson<BuilderStartResponse>("/builder/start", { request }),
  answer: (session_id: string, answer: string) =>
    postJson<BuilderAnswerResponse>("/builder/answer", { session_id, answer }),
  deploy: (session_id: string) =>
    postJson<{ status: string; name?: string }>("/builder/deploy", { session_id }),
  cancel: (session_id: string) =>
    postJson<{ status: string }>("/builder/cancel", { session_id }),
};
```

- [ ] **Step 3: Typecheck**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add ui/src/api/builder.ts
git commit -m "feat(ui): typed builder API client"
```

---

### Task 9: Zustand store for builder state

**Files:**
- Create: `ui/src/stores/builder.ts`

- [ ] **Step 1: Create ui/src/stores/builder.ts**

```typescript
// ui/src/stores/builder.ts
import { create } from "zustand";
import { builderApi, BuilderPreview } from "../api/builder";

export type BuilderPhase =
  | "idle"
  | "asking"       // wizard asking questions
  | "generating"   // working on preview (server-side)
  | "previewing"   // showing preview, awaiting confirm
  | "deploying"    // committing to disk + runtime
  | "done"
  | "error";

interface BuilderState {
  phase: BuilderPhase;
  sessionId: string | null;
  request: string;
  question: string | null;
  step: number;
  totalSteps: number;
  preview: BuilderPreview | null;
  error: string | null;

  start: (request: string) => Promise<void>;
  answer: (text: string) => Promise<void>;
  deploy: () => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
}

export const useBuilderStore = create<BuilderState>((set, get) => ({
  phase: "idle",
  sessionId: null,
  request: "",
  question: null,
  step: 0,
  totalSteps: 0,
  preview: null,
  error: null,

  start: async (request) => {
    set({ phase: "asking", request, error: null });
    try {
      const r = await builderApi.start(request);
      set({
        sessionId: r.session_id,
        question: r.question,
        totalSteps: r.total_steps,
        step: 0,
      });
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  answer: async (text) => {
    const sid = get().sessionId;
    if (!sid) return;
    try {
      const r = await builderApi.answer(sid, text);
      if (r.done && r.preview) {
        set({ phase: "previewing", preview: r.preview, question: null });
      } else {
        set({
          question: r.question ?? null,
          step: r.step ?? get().step + 1,
        });
      }
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  deploy: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ phase: "deploying" });
    try {
      await builderApi.deploy(sid);
      set({ phase: "done" });
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  cancel: async () => {
    const sid = get().sessionId;
    if (sid) await builderApi.cancel(sid).catch(() => {});
    get().reset();
  },

  reset: () =>
    set({
      phase: "idle",
      sessionId: null,
      request: "",
      question: null,
      step: 0,
      totalSteps: 0,
      preview: null,
      error: null,
    }),
}));
```

- [ ] **Step 2: Typecheck**

```bash
cd ui && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add ui/src/stores/builder.ts
git commit -m "feat(ui): Zustand store for builder state"
```

---

### Task 10: BuilderPanel component with progress animation + 5 starter examples

**Files:**
- Create: `ui/src/components/Builder/BuilderPanel.tsx`
- Create: `ui/src/components/Builder/BuilderProgress.tsx`
- Create: `ui/src/components/Builder/BuilderPreview.tsx`
- Create: `ui/src/components/Builder/StarterExamples.tsx`
- Modify: `ui/src/App.tsx` or main layout to mount Builder panel behind a mode switch

**Starter examples** (show as clickable prompts когда phase=idle):
1. "Напомни пить воду каждые 2 часа"
2. "Веди дневник настроения — спрашивай раз в день"
3. "Таймер для плова — 30 минут с напоминаниями"
4. "Трекер ежедневных трат — голосом"
5. "Мониторинг курса биткоина — оповещай при падении 5%"

Click на example → вставляется в input → user может нажать Enter или отредактировать.

- [ ] **Step 1: Create BuilderProgress.tsx**

```tsx
// ui/src/components/Builder/BuilderProgress.tsx
import { useBuilderStore } from "../../stores/builder";

const PHASE_LABEL: Record<string, string> = {
  idle: "Готов",
  asking: "Задаю уточняющие вопросы",
  generating: "Анализирую запрос",
  previewing: "Готовлю превью",
  deploying: "Собираю и запускаю",
  done: "Готово!",
  error: "Ошибка",
};

export function BuilderProgress() {
  const { phase, step, totalSteps } = useBuilderStore();
  return (
    <div className="builder-progress">
      <div className="phase-label">{PHASE_LABEL[phase]}</div>
      {totalSteps > 0 && (
        <div className="step-dots">
          {Array.from({ length: totalSteps }).map((_, i) => (
            <span
              key={i}
              className={`dot ${i < step ? "filled" : ""} ${i === step ? "current" : ""}`}
            />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create BuilderPreview.tsx**

```tsx
// ui/src/components/Builder/BuilderPreview.tsx
import { useBuilderStore } from "../../stores/builder";

export function BuilderPreview() {
  const { preview, deploy, cancel } = useBuilderStore();
  if (!preview) return null;
  return (
    <div className="builder-preview">
      <h3>Превью агента</h3>
      <p><strong>Название:</strong> {preview.name}</p>
      <p><strong>Описание:</strong> {preview.description}</p>
      <p><strong>Тип:</strong> {preview.template ?? "agent"}</p>
      <pre>{JSON.stringify(preview.config, null, 2)}</pre>
      <div className="actions">
        <button onClick={deploy}>Запустить</button>
        <button onClick={cancel}>Отменить</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2.5: Create StarterExamples.tsx**

```tsx
// ui/src/components/Builder/StarterExamples.tsx
const STARTER_EXAMPLES = [
  "Напомни пить воду каждые 2 часа",
  "Веди дневник настроения — спрашивай раз в день",
  "Таймер для плова — 30 минут с напоминаниями",
  "Трекер ежедневных трат — голосом",
  "Мониторинг курса биткоина — оповещай при падении 5%",
];

interface Props {
  onPick: (text: string) => void;
}

export function StarterExamples({ onPick }: Props) {
  return (
    <div className="starter-examples">
      <p className="label">Или начни с примера:</p>
      <div className="example-list">
        {STARTER_EXAMPLES.map((ex) => (
          <button key={ex} onClick={() => onPick(ex)} className="example-chip">
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create BuilderPanel.tsx**

```tsx
// ui/src/components/Builder/BuilderPanel.tsx
import { useState } from "react";
import { useBuilderStore } from "../../stores/builder";
import { BuilderProgress } from "./BuilderProgress";
import { BuilderPreview } from "./BuilderPreview";

export function BuilderPanel() {
  const { phase, question, answer, start, reset, error } = useBuilderStore();
  const [text, setText] = useState("");

  const submit = async () => {
    if (!text.trim()) return;
    if (phase === "idle") await start(text);
    else if (phase === "asking") await answer(text);
    setText("");
  };

  return (
    <div className="builder-panel">
      <BuilderProgress />
      {error && <div className="error">{error}</div>}

      {phase === "idle" && (
        <div>
          <p>Скажи или напиши идею агента:</p>
          <input
            placeholder="напр. 'напомни пить воду каждые 2 часа'"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <button onClick={submit}>Создать</button>
          <StarterExamples onPick={(ex) => setText(ex)} />
        </div>
      )}

      {phase === "asking" && question && (
        <div>
          <p><strong>{question}</strong></p>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            autoFocus
          />
          <button onClick={submit}>Ответить</button>
        </div>
      )}

      {phase === "previewing" && <BuilderPreview />}

      {phase === "done" && (
        <div>
          <p>Агент запущен</p>
          <button onClick={reset}>Создать ещё</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Wire BuilderPanel into main layout**

Find the main mode switcher (probably `ui/src/components/Layout/ModeSelector.tsx`). Add "Builder" mode.

Run: `grep -rn "ModeSelector" ui/src/`

Add Builder mode icon + render condition for `<BuilderPanel />`.

- [ ] **Step 5: Typecheck + run dev server**

```bash
cd ui && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add ui/src/components/Builder/ ui/src/components/Layout/ModeSelector.tsx
git commit -m "feat(ui): BuilderPanel with progress + preview + manual fallback"
```

---

## Chunk 5: End-to-End Test + Demo Harness

### Task 11: Automated E2E test — simulated voice → deployed skill in <60s

**Files:**
- Create: `tests/e2e/test_builder_voice_e2e.py`

- [ ] **Step 1: Write test**

```python
# tests/e2e/test_builder_voice_e2e.py
"""End-to-end builder: simulated STT input → deployed skill, wall-clock <60s."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore
from kernel.main import create_app


@pytest.mark.asyncio
async def test_builder_e2e_water_reminder(tmp_path, monkeypatch):
    """Simulate: voice → "напомни пить воду" → 3 answers → deploy → skill on disk."""
    # Mock intent classifier (no LLM needed)
    monkeypatch.setattr(
        "kernel.builder.flow.classify_intent",
        lambda req: type("I", (), {"type": "skill", "template": "reminder", "confidence": 0.9, "reason": "mock"}),
    )

    app = create_app()
    agents_dir = tmp_path / "agents"
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    app.state.builder_flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=agents_dir,
        skill_executor=executor,
    )

    start_time = time.monotonic()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/builder/start", json={"request": "напомни пить воду каждые 2 часа"})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        total = r.json()["total_steps"]

        answers = ["каждые 2 часа", "с 9 утра до 10 вечера", "голосом"]
        for i in range(total):
            a = answers[i] if i < len(answers) else "default"
            r = await c.post("/builder/answer", json={"session_id": sid, "answer": a})
            assert r.status_code == 200

        r = await c.post("/builder/deploy", json={"session_id": sid})
        assert r.status_code == 200
        assert r.json()["status"] == "deployed"

    elapsed = time.monotonic() - start_time
    assert elapsed < 60.0, f"Flow took {elapsed:.1f}s — exceeds 60s budget"

    # Verify skill files on disk
    skill_dirs = list(agents_dir.iterdir())
    assert len(skill_dirs) == 1
    assert (skill_dirs[0] / "manifest.yaml").exists()
    assert (skill_dirs[0] / "skill.yaml").exists()
```

- [ ] **Step 2: Run the test**

```bash
uv run --with pytest --with pytest-asyncio --with httpx pytest tests/e2e/test_builder_voice_e2e.py -v
```

Expected: PASS with elapsed time logged.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_builder_voice_e2e.py
git commit -m "test(e2e): builder voice-to-deployed-skill under 60s"
```

---

### Task 12: Demo video harness — CLI script to capture 60s flow

**Files:**
- Create: `tools/demo_builder.py`

- [ ] **Step 1: Create demo script**

```python
# tools/demo_builder.py
"""Demo flow — prints timestamped trace of a builder session for screen recording.

Usage: uv run python tools/demo_builder.py --request "напомни пить воду каждые 2 часа"
"""

import argparse
import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

from kernel.builder.flow import BuilderFlow
from kernel.builder.session_store import SessionStore


async def demo(request: str) -> None:
    executor = MagicMock()
    executor.load_skill = MagicMock()
    executor.get_skill_info = MagicMock(return_value={"config": {}})
    flow = BuilderFlow(
        session_store=SessionStore(),
        agents_dir=Path("agents"),
        skill_executor=executor,
    )

    start = time.monotonic()

    def log(msg: str) -> None:
        elapsed = time.monotonic() - start
        print(f"[{elapsed:5.1f}s] {msg}")

    log(f"USER: {request}")
    r = flow.start(request)
    sid = r["session_id"]
    log(f"JARVIS: {r['question']}")

    canned = ["каждые 2 часа", "с 9 утра", "голосом"]
    for a in canned[: r["total_steps"]]:
        log(f"USER: {a}")
        resp = flow.answer(sid, a)
        if resp.get("done"):
            log(f"JARVIS: Я создам {resp['preview']['name']}. Запускать?")
        else:
            log(f"JARVIS: {resp['question']}")

    log("USER: да, запускай")
    result = await flow.deploy(sid)
    log(f"JARVIS: Готово! {result.get('name', '')} запущен.")
    log(f"Total time: {time.monotonic() - start:.1f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--request", default="напомни пить воду каждые 2 часа")
    args = p.parse_args()
    asyncio.run(demo(args.request))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
uv run python tools/demo_builder.py
```

Expected: timestamped output showing <5s end-to-end (without voice I/O). With voice: target <60s.

- [ ] **Step 3: Commit**

```bash
git add tools/demo_builder.py
git commit -m "feat(tools): demo script for builder flow timing trace"
```

---

## Final Review

After all tasks:

1. Run full test suite:
   ```bash
   uv run --with pytest --with pytest-asyncio --with httpx pytest tests/ -x
   ```

2. Record 60-second demo video (real human voice, no cuts) creating a reminder skill. This is the **success criterion** — no video = pilot not done.

3. Update VISION.md → Phase 8 (or relevant section) to mark voice builder pilot as ✅ DONE.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| STT mishears trigger phrase | `_detect_builder_trigger` accepts multiple patterns + confirmation question before action |
| LLM intent classifier too slow (>5s) | Regex fallback already in `intent_classifier.py`; prefer it for pilot |
| F5-TTS slow on first call (cold load) | Pre-load on backend startup (load_models already exists); measure cold vs warm |
| Deploy fails mid-flow | `deployer.py` already has rollback — verify rollback cleans session too |
| User says ambiguous "нет" vs "переделай" vs silence | Deterministic keywords; fallback: confirm again after 3s timeout |

---

## Out-of-scope / Future Work (Tracked Separately)

- **Template gallery** — expand beyond 5 skill templates to 20+ concrete ready-to-remix examples (cooking timer, expense tracker, etc.)
- **Share-to-reels** — screen recorder + TikTok-format overlay as one-click action after deploy
- **Undo via voice mid-wizard** — currently only `/cancel` at end; "отмени последний ответ" would need stack in SessionStore
- **Agent generation** (Python code via LLM) — intent_classifier already detects this path; out of pilot scope, re-enable after skills work reliably
- **Mobile platform** — separate plan; BuilderFlow HTTP API will be reusable
