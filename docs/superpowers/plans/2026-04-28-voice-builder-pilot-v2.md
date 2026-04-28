# voice-builder-pilot v2 — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a voice-first enhancement layer on top of the existing text-based builder pilot — new L1-layout screen with mic-orb-centred capture, browser RMS-VAD, single-shot LLM extraction (A4), TTS-readback wizard prompts, and a final preview readback with voice-confirm. Wraps the existing `BuilderFlow` Python orchestrator without rewriting it.

**Architecture:** Frontend extends the existing `useBuilderStore` Zustand state and `builderApi` typed client; mounts `VoiceBuilderScreen.tsx` at `mode === "builder"` (replaces the existing `BuilderPanel.tsx`). Backend adds two new endpoints — `POST /builder/extract` (LLM single-shot) and `POST /voice/transcribe` (in-process Whisper + scipy resample) — and one shared helper `_question_to_key` that both `_build_spec` and the extractor consume. F5 prewarm is wired into the FastAPI startup hook.

**Tech Stack:** Python 3.12 / FastAPI (existing), pytest + pytest-asyncio + httpx; React 19 + TypeScript + Zustand (existing); Vitest. Browser audio capture via MediaRecorder + AudioContext + manual RMS-VAD. Whisper STT via faster-whisper (existing `kernel.voice.stt.SpeechToText`). TTS via existing `/tts/speak`.

**Spec:** [docs/superpowers/specs/2026-04-28-voice-builder-pilot-design.md](../specs/2026-04-28-voice-builder-pilot-design.md)

**Estimate:** 7-8 days solo. Order optimised so the backend pieces land first (frontend can target a real endpoint instead of a stub by Day 3).

---

## Chunk 1: Backend foundation — `_question_to_key` + `name_hint` plumbing

**Why first:** Both downstream backend pieces (`/builder/extract` and the unchanged-but-refactored `_build_spec`) depend on the canonical question-to-key mapping. Locking it as a tested helper before anyone consumes it prevents duplication and keeps the parametrized test the single source of truth.

### Task 1: Extract `_question_to_key` helper into `wizard.py`

**Files:**
- Modify: `kernel/builder/wizard.py`
- Create: `tests/kernel/builder/test_question_to_key.py`

- [ ] **Step 1: Write the failing parametrized test**

```python
# tests/kernel/builder/test_question_to_key.py
"""Helper that maps a wizard question text to its config key.

Authoritative test — drift in either the helper or the question
strings in `_skill_questions` will fail this and force sync.
"""
from __future__ import annotations

import pytest

from kernel.builder.wizard import _question_to_key


@pytest.mark.parametrize(
    "question,expected",
    [
        # tracker
        ("Какая дневная цель?", "goal"),
        ("Как часто напоминать?", "interval"),
        ("Куда отправлять уведомления — голосом или в телеграм?", "notify_channel"),
        # reminder
        ("В какое время начинать и заканчивать?", "time_window"),
        # monitor
        ("Какой URL или сервис проверять?", "target"),
        ("Как часто проверять?", "interval"),
        # notifier
        ("При каком условии уведомлять?", "trigger"),
        ("Куда отправлять — голосом или в телеграм?", "notify_channel"),
        # logger
        ("Какие события записывать?", "categories"),
        # unknown question falls into the param_N bucket
        ("Что-то совершенно другое?", ""),
    ],
)
def test_question_to_key(question: str, expected: str) -> None:
    assert _question_to_key(question) == expected
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_question_to_key.py -v`

Expected: `ImportError: cannot import name '_question_to_key' from 'kernel.builder.wizard'` or equivalent.

- [ ] **Step 3: Implement the helper in `kernel/builder/wizard.py`**

Add at the bottom of `kernel/builder/wizard.py` (after `_slugify`):

```python
def _question_to_key(question: str) -> str:
    """Map a wizard question text to the config key its answer populates.

    Lowercases the question once so substring needles are case-insensitive
    (wizard questions start with capitalised words like "Куда" / "Какая").

    Order matters: `trigger` is checked BEFORE `notify_channel` because the
    notifier question "При каком условии уведомлять?" contains both "услов"
    and "уведом"; tighter / earlier matches win.

    Returns "" for unrecognised questions so they fall into the param_N
    bucket downstream (matching the historical `_build_spec` behaviour).
    """
    q = question.lower()
    if "часто" in q or "interval" in q:
        return "interval"
    elif "цел" in q or "goal" in q:
        return "goal"
    elif "услов" in q or "trigger" in q:
        return "trigger"
    elif "уведом" in q or "notify" in q or "куда" in q:
        return "notify_channel"
    elif "url" in q or "сервис" in q:
        return "target"
    elif "событ" in q or "категор" in q:
        return "categories"
    elif "врем" in q or "time" in q:
        return "time_window"
    return ""
```

- [ ] **Step 4: Run the test, verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_question_to_key.py -v`

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/wizard.py tests/kernel/builder/test_question_to_key.py
git commit -m "feat(builder): extract _question_to_key helper with parametrized test"
```

---

### Task 2: Refactor `WizardSession.build_spec` and `BuilderFlow._build_spec` to use the helper

**Files:**
- Modify: `kernel/builder/wizard.py:39-59`
- Modify: `kernel/builder/flow.py:184-208`
- Create: `tests/kernel/builder/test_build_spec_helper_parity.py`

- [ ] **Step 1: Write the failing parity test**

```python
# tests/kernel/builder/test_build_spec_helper_parity.py
"""Both _build_spec implementations must produce the same config dict
when fed the same questions+answers. Locks the helper-refactor.
"""
from __future__ import annotations

from kernel.builder.flow import BuilderFlow
from kernel.builder.intent_classifier import IntentResult
from kernel.builder.session_store import BuilderSession
from kernel.builder.wizard import WizardSession


def _make_intent() -> IntentResult:
    return IntentResult(type="skill", template="tracker", confidence=0.9, reason="test")


def test_helper_drives_config_keys_consistently() -> None:
    questions = [
        "Какая дневная цель?",
        "Как часто напоминать?",
        "Куда отправлять уведомления — голосом или в телеграм?",
    ]
    answers = ["2 литра", "каждые 2 часа", "в чат"]

    # WizardSession path
    ws = WizardSession(request="трекер воды", intent=_make_intent(), questions=questions)
    for a in answers:
        ws.answer(a)
    spec_ws = ws.build_spec()

    # BuilderFlow path
    bs = BuilderSession(
        session_id="x",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
        questions=questions,
        answers=answers,
        step=len(answers),
    )
    flow = BuilderFlow.__new__(BuilderFlow)  # bypass __init__ — we only test _build_spec
    spec_flow = flow._build_spec(bs)

    assert spec_ws["config"] == spec_flow["config"]
    assert spec_ws["config"] == {
        "goal": "2 литра",
        "interval": "каждые 2 часа",
        "notify_channel": "в чат",
    }
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_build_spec_helper_parity.py -v`

Expected: FAIL — current code uses divergent inline substring rules; assertion mismatch.

Actually — verify: today both implementations *probably* return the same dict for these inputs because they share the inline rules. Confirm with a print or run `pytest -v`. If it accidentally passes, that's fine — the test still locks future drift.

- [ ] **Step 3: Refactor both implementations to call `_question_to_key`**

In `kernel/builder/wizard.py`, replace the body of `WizardSession.build_spec` (lines 39-59):

```python
    def build_spec(self) -> dict[str, Any]:
        """Build structured spec from answers."""
        spec: dict[str, Any] = {
            "name": _slugify(self.request),
            "description": self.request,
            "type": self.intent.type,
            "template": self.intent.template,
        }
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(self.questions, self.answers)):
            key = _question_to_key(q)
            if key:
                config[key] = a
            else:
                config[f"param_{i}"] = a
        spec["config"] = config
        return spec
```

In `kernel/builder/flow.py`, replace the body of `BuilderFlow._build_spec` (lines 184-208):

```python
    def _build_spec(self, session: BuilderSession) -> dict[str, Any]:
        """Materialise a skill spec from session answers (uses shared helper)."""
        from kernel.builder.wizard import _question_to_key

        # Prefer LLM-extracted name_hint when present (set by /builder/extract);
        # fall back to slugify-of-request for the existing text-pilot path.
        name_source = (
            session.name_hint
            if getattr(session, "name_hint", None)
            else session.request
        )
        name = re.sub(r"[^\w\s-]", "", name_source.lower()).strip()
        name = re.sub(r"[\s_]+", "-", name)[:40].strip("-")
        if not name:
            raise ValueError(
                f"Cannot derive a valid skill name from request: {session.request!r}"
            )
        config: dict[str, Any] = {}
        for i, (q, a) in enumerate(zip(session.questions, session.answers)):
            key = _question_to_key(q)
            if key:
                config[key] = a
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

(`re` is already imported at the top of `flow.py`.)

- [ ] **Step 4: Run all builder tests, verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/ -v`

Expected: all green (the new test plus the existing `test_session_store.py`, `test_flow.py`, etc.).

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/wizard.py kernel/builder/flow.py tests/kernel/builder/test_build_spec_helper_parity.py
git commit -m "refactor(builder): both build_spec paths consume _question_to_key helper"
```

---

### Task 3: Add `name_hint` field to `BuilderSession`

**Files:**
- Modify: `kernel/builder/session_store.py`
- Modify: `tests/kernel/builder/test_session_store.py`

- [ ] **Step 1: Append a failing test**

Append to `tests/kernel/builder/test_session_store.py`:

```python
def test_session_carries_name_hint() -> None:
    """name_hint is an optional attribute used by /builder/extract to
    pre-populate the LLM's slug suggestion before _build_spec runs.
    """
    from kernel.builder.session_store import BuilderSession

    s = BuilderSession(
        session_id="abc",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
        name_hint="treker-vody",
    )
    assert s.name_hint == "treker-vody"


def test_session_default_name_hint_is_none() -> None:
    from kernel.builder.session_store import BuilderSession

    s = BuilderSession(
        session_id="abc",
        request="трекер воды",
        intent_type="skill",
        template="tracker",
    )
    assert s.name_hint is None
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_session_store.py -v`

Expected: TypeError or AttributeError on `name_hint`.

- [ ] **Step 3: Add the field**

In `kernel/builder/session_store.py`, find the `BuilderSession` dataclass. Add the field after `template`:

```python
@dataclass
class BuilderSession:
    """Tracks state of one builder flow from request → deploy."""

    session_id: str
    request: str
    intent_type: str  # "skill" | "agent"
    template: str | None
    name_hint: str | None = None  # NEW — populated by /builder/extract
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    step: int = 0
    spec: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.monotonic)
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/ -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/session_store.py tests/kernel/builder/test_session_store.py
git commit -m "feat(builder): BuilderSession.name_hint for /builder/extract plumbing"
```

---

## Chunk 2: Backend extractor — `extractor.py` module + `/builder/extract` endpoint

**Why second:** Builds on Chunk 1's helper + name_hint field. Frontend can stub the endpoint until landed; backend tests don't need anything beyond Chunk 1.

### Task 4: Create `extractor.py` module skeleton with the LLM prompt as a module constant

**Files:**
- Create: `kernel/builder/extractor.py`
- Create: `tests/kernel/builder/test_extractor.py`

- [ ] **Step 1: Write the failing test for the prompt constant**

```python
# tests/kernel/builder/test_extractor.py
"""Tests for the LLM-driven /builder/extract logic.

The actual LLM call is mocked — we test the wiring (template
validation, BuilderSession mutation contract, fallback behaviour).
"""
from __future__ import annotations

import pytest

from kernel.builder import extractor


def test_system_prompt_lists_all_template_keys() -> None:
    """Verbatim prompt mentions every template + every config key the
    helper recognises. Drift in either direction breaks A4 fast-path.
    """
    p = extractor.LLM_SYSTEM_PROMPT
    for tmpl in ("tracker", "reminder", "monitor", "notifier", "logger"):
        assert tmpl in p
    for key in (
        "interval", "goal", "notify_channel", "time_window",
        "target", "trigger", "categories",
    ):
        assert key in p
    assert "STRICT JSON" in p
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_extractor.py -v`

Expected: `ModuleNotFoundError: No module named 'kernel.builder.extractor'`.

- [ ] **Step 3: Create the module with the prompt**

Create `kernel/builder/extractor.py`:

```python
"""LLM-driven single-shot extraction over the wizard schema.

Used by `POST /builder/extract` to populate as many wizard answers as
possible from a single user utterance — the A4 fast-path. When the LLM
returns enough data to fill every wizard slot, we skip the wizard
entirely and produce a complete spec; otherwise we pre-populate the
session and return the first un-extracted question to the caller.

Falls back to the regular `BuilderFlow.start()` path if the LLM is
unavailable, returns invalid JSON, or selects an unknown template.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from kernel.builder.session_store import BuilderSession, SessionStore
from kernel.builder.wizard import _question_to_key, create_wizard
from kernel.builder.intent_classifier import IntentResult

logger = logging.getLogger(__name__)


LLM_SYSTEM_PROMPT = """\
You are KALI's skill spec extractor. The user describes a Russian (or
English) automation idea; your job is to extract every parameter that
can be derived from their words and return a complete or partial skill
spec.

Templates and their config keys:
- tracker:   interval (e.g. "2 часа", "час"), goal (e.g. "2 литра"), notify_channel ("голос" | "телеграм" | "чат")
- reminder:  interval, time_window (e.g. "9-22", "будни")
- monitor:   target (URL or service), interval
- notifier:  trigger, notify_channel
- logger:    categories

Use ONLY data the user provided. Do NOT invent values. If a parameter
is not stated, omit the key entirely (do not write null).

Respond with STRICT JSON only, no prose:
{
  "type": "skill",
  "template": "<one of: tracker | reminder | monitor | notifier | logger>",
  "name_hint": "<kebab-case slug, lowercase, ≤40 chars>",
  "extracted": {
    "interval": "<string>",
    "goal": "<string>",
    "notify_channel": "<string>",
    "time_window": "<string>",
    "target": "<string>",
    "trigger": "<string>",
    "categories": "<string>"
  },
  "confidence": <0.0-1.0>
}

Only include keys you actually extracted under "extracted".
"""


_VALID_TEMPLATES = frozenset({"tracker", "reminder", "monitor", "notifier", "logger"})


def _call_llm(request: str) -> dict[str, Any] | None:
    """Run the extractor prompt against the configured LLM provider.

    Returns the parsed JSON dict on success, or None if no provider is
    configured / call fails / response is not valid JSON.
    """
    try:
        from kernel.builder.agent_generator import _detect_provider, _call_llm as call
    except ImportError:
        logger.warning("agent_generator not importable — extractor disabled")
        return None

    provider_info = _detect_provider()
    if provider_info is None:
        return None

    provider, model = provider_info
    try:
        raw = call(provider, model, LLM_SYSTEM_PROMPT, request)
    except Exception as exc:
        logger.warning("Extractor LLM call failed (%s): %s", provider, exc)
        return None

    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Extractor LLM returned invalid JSON: %s — %s", exc, raw[:200])
        return None
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_extractor.py -v`

Expected: 1 passed (the prompt-content test).

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/extractor.py tests/kernel/builder/test_extractor.py
git commit -m "feat(builder): extractor module skeleton with verbatim LLM prompt"
```

---

### Task 5: Implement `extract_spec` — the main entry point that mutates a `BuilderSession`

**Files:**
- Modify: `kernel/builder/extractor.py`
- Modify: `tests/kernel/builder/test_extractor.py`

- [ ] **Step 1: Append failing tests covering the mutation contract**

Append to `tests/kernel/builder/test_extractor.py`:

```python
from unittest.mock import patch

from kernel.builder.session_store import SessionStore


def _stub_llm(template: str, name_hint: str, extracted: dict[str, str]):
    """Return a function suitable for monkeypatching extractor._call_llm."""
    def _fake(_request: str) -> dict[str, Any]:
        return {
            "type": "skill",
            "template": template,
            "name_hint": name_hint,
            "extracted": extracted,
            "confidence": 0.9,
        }
    return _fake


def test_extract_complete_returns_full_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three tracker fields extracted → complete=True, no wizard turn needed."""
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "interval": "2 часа",
            "goal": "2 литра",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер воды два литра каждые два часа в чат",
        session_store=store,
    )

    assert result["complete"] is True
    assert result["session_id"] in store._sessions
    spec = result["spec"]
    assert spec["template"] == "tracker"
    assert spec["name"] == "treker-vody"
    assert spec["config"]["interval"] == "2 часа"
    assert spec["config"]["goal"] == "2 литра"
    assert spec["config"]["notify_channel"] == "чат"


def test_extract_partial_pre_populates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two of three tracker fields extracted → complete=False, wizard
    resumes at the first un-extracted question.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "interval": "2 часа",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер воды каждые два часа в чат",
        session_store=store,
    )

    assert result["complete"] is False
    sid = result["session_id"]
    session = store.get(sid)

    # Tracker question order: ["Какая дневная цель?", "Как часто напоминать?",
    # "Куда отправлять уведомления — голосом или в телеграм?"]
    # Only "часто" and "куда" were extracted; "цель" stays missing → wizard
    # resumes at index 0 (the goal question), with answers pre-populated for
    # the other two slots? NO — extraction stops at the first missing field
    # in question order to preserve the wizard sequence.
    # Goal is question[0] → missing → step=0 → answers=[] (extracted values
    # are stored but only those *up to* the first missing slot — there are
    # none here, since goal is first).
    assert session.step == 0
    assert session.answers == []
    assert result["next_question"] == "Какая дневная цель?"
    # partial_spec still surfaces extracted values via build_spec on the
    # session object — but with empty answers list, _build_spec produces
    # an empty config. So partial_spec shows just the name + template.
    assert result["partial_spec"]["template"] == "tracker"


def test_extract_partial_fills_in_question_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Goal extracted but interval missing → wizard resumes at interval (q1),
    answers pre-populated for goal (q0) only.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("tracker", "treker-vody", {
            "goal": "2 литра",
            "notify_channel": "чат",
        }),
    )
    store = SessionStore()
    result = extractor.extract_spec(
        request="трекер 2 литра в чат",
        session_store=store,
    )

    assert result["complete"] is False
    sid = result["session_id"]
    session = store.get(sid)
    assert session.step == 1
    assert session.answers == ["2 литра"]
    assert result["next_question"] == "Как часто напоминать?"


def test_extract_invalid_template_falls_back_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM picks an unknown template → fallback creates a session via
    classify_intent + create_wizard like /builder/start would.
    """
    monkeypatch.setattr(
        extractor,
        "_call_llm",
        _stub_llm("nonsense", "x", {}),
    )
    monkeypatch.setattr(
        "kernel.builder.extractor.classify_intent",
        lambda r: IntentResult(type="skill", template="reminder", confidence=0.9, reason="mock"),
    )
    store = SessionStore()
    result = extractor.extract_spec(request="напомни кушать", session_store=store)

    assert result["complete"] is False
    session = store.get(result["session_id"])
    assert session.template == "reminder"
    assert session.step == 0
    assert session.answers == []


def test_extract_llm_unavailable_falls_back_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """No LLM provider → fallback to /builder/start equivalent."""
    monkeypatch.setattr(extractor, "_call_llm", lambda r: None)
    monkeypatch.setattr(
        "kernel.builder.extractor.classify_intent",
        lambda r: IntentResult(type="skill", template="logger", confidence=0.9, reason="mock"),
    )
    store = SessionStore()
    result = extractor.extract_spec(request="дневник настроения", session_store=store)

    assert result["complete"] is False
    assert result["next_question"] == "Какие события записывать?"
```

- [ ] **Step 2: Run, verify failures**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_extractor.py -v`

Expected: 5 failing (`AttributeError: module 'kernel.builder.extractor' has no attribute 'extract_spec'`).

- [ ] **Step 3: Implement `extract_spec`**

Append to `kernel/builder/extractor.py`:

```python
from kernel.builder.intent_classifier import classify_intent  # for fallback


def extract_spec(
    request: str,
    session_store: SessionStore,
) -> dict[str, Any]:
    """Single-shot extract → either a complete spec or a partially-filled session.

    Args:
        request: User's natural-language description.
        session_store: Where the new session is created.

    Returns:
        Dict matching the `/builder/extract` HTTP contract — see spec.
    """
    llm_result = _call_llm(request)

    # Fallback: LLM unavailable, returned non-dict / invalid JSON, or unknown template.
    if (
        llm_result is None
        or not isinstance(llm_result, dict)
        or llm_result.get("template") not in _VALID_TEMPLATES
    ):
        return _fallback_to_start(request, session_store)

    template = llm_result["template"]
    name_hint = llm_result.get("name_hint") or None
    extracted = llm_result.get("extracted") or {}
    if not isinstance(extracted, dict):
        extracted = {}  # defensive against LLM emitting a list / scalar

    intent = IntentResult(
        type="skill",
        template=template,
        confidence=float(llm_result.get("confidence", 0.75)),
        reason="LLM extractor",
    )
    wizard = create_wizard(request, intent)

    # Walk questions in order, fill answers from `extracted` until the first
    # missing field; preserves wizard order so the user resumes at the right
    # step.
    sid = session_store.create(
        request=request,
        intent_type="skill",
        template=template,
    )
    session = session_store.get(sid)
    session.questions = wizard.questions
    session.name_hint = name_hint

    for question in session.questions:
        key = _question_to_key(question)
        if key and key in extracted:
            session.answers.append(extracted[key])
            session.step += 1
        else:
            break

    if session.step == len(session.questions):
        # All extracted — build spec immediately.
        from kernel.builder.flow import BuilderFlow

        flow = BuilderFlow.__new__(BuilderFlow)
        spec = flow._build_spec(session)
        session.spec = spec
        return {"complete": True, "session_id": sid, "spec": spec}

    # Partial — return next question + partial preview spec.
    from kernel.builder.flow import BuilderFlow

    flow = BuilderFlow.__new__(BuilderFlow)
    partial_spec = flow._build_spec(session)

    return {
        "complete": False,
        "session_id": sid,
        "step": session.step,
        "total_steps": len(session.questions),
        "questions": list(session.questions),  # full list — UI uses this for editField
        "next_question": session.current_question,
        "partial_spec": partial_spec,
    }


def _fallback_to_start(request: str, session_store: SessionStore) -> dict[str, Any]:
    """Mirror BuilderFlow.start() — used when LLM extraction fails."""
    intent = classify_intent(request)
    if intent.type != "skill":
        # Pilot scope guard — same as BuilderFlow.start().
        raise ValueError(
            f"Agent generation out of pilot scope (got intent: {intent.type})"
        )
    wizard = create_wizard(request, intent)
    sid = session_store.create(
        request=request,
        intent_type="skill",
        template=intent.template,
    )
    session = session_store.get(sid)
    session.questions = wizard.questions

    from kernel.builder.flow import BuilderFlow

    flow = BuilderFlow.__new__(BuilderFlow)
    partial_spec = flow._build_spec(session)

    return {
        "complete": False,
        "session_id": sid,
        "step": 0,
        "total_steps": len(session.questions),
        "questions": list(session.questions),  # full list — UI uses this for editField
        "next_question": session.current_question,
        "partial_spec": partial_spec,
    }
```

(`BuilderFlow.__new__(BuilderFlow)` is used to call the `_build_spec` method without going through `__init__`'s required arguments — same trick as the existing `test_build_spec_helper_parity.py`.)

- [ ] **Step 4: Run, verify all pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/builder/test_extractor.py -v`

Expected: 6 passed (1 from earlier + 5 new).

- [ ] **Step 5: Commit**

```bash
git add kernel/builder/extractor.py tests/kernel/builder/test_extractor.py
git commit -m "feat(builder): extract_spec — A4 fast-path with mutation contract + fallback"
```

---

### Task 6: Add `POST /builder/extract` HTTP endpoint

**Files:**
- Modify: `kernel/main.py` (after the existing `@app.post("/builder/start")` block)
- Modify: `tests/kernel/test_builder_endpoints.py`

- [ ] **Step 1: Append failing endpoint tests**

Append to `tests/kernel/test_builder_endpoints.py`:

```python
from unittest.mock import AsyncMock, MagicMock


async def test_extract_endpoint_complete_path(client, monkeypatch):
    """Full extraction → 200 with spec field, session_id available for /deploy."""
    monkeypatch.setattr(
        "kernel.builder.extractor._call_llm",
        lambda r: {
            "type": "skill",
            "template": "tracker",
            "name_hint": "treker-vody",
            "extracted": {
                "interval": "2 часа",
                "goal": "2 литра",
                "notify_channel": "чат",
            },
            "confidence": 0.9,
        },
    )
    r = await client.post(
        "/builder/extract",
        json={"request": "трекер воды два литра каждые 2 часа в чат"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is True
    assert data["session_id"]
    assert data["spec"]["name"] == "treker-vody"
    assert data["spec"]["config"]["interval"] == "2 часа"


async def test_extract_endpoint_partial_path(client, monkeypatch):
    monkeypatch.setattr(
        "kernel.builder.extractor._call_llm",
        lambda r: {
            "type": "skill",
            "template": "tracker",
            "name_hint": "treker-vody",
            "extracted": {"goal": "2 литра"},
            "confidence": 0.7,
        },
    )
    r = await client.post(
        "/builder/extract",
        json={"request": "трекер 2 литра"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is False
    assert data["next_question"] == "Как часто напоминать?"
    assert data["step"] == 1
    assert data["total_steps"] == 3


async def test_extract_endpoint_rejects_empty_request(client):
    r = await client.post("/builder/extract", json={"request": ""})
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_builder_endpoints.py -v -k extract`

Expected: 404 / route not found.

- [ ] **Step 3: Wire the endpoint**

In `kernel/main.py`, find the existing `/builder/start` endpoint (around line 1535). Insert a new endpoint immediately after the `@app.post("/builder/start")` block:

```python
    @app.post("/builder/extract")
    async def builder_extract(request: Request) -> Any:
        """A4 fast-path: single-shot LLM extraction over the wizard schema.

        Tries to populate every wizard answer from the user utterance in
        one LLM call. On full match returns the complete spec; on partial
        match returns a session pre-populated up to the first missing
        field plus the next question; on failure / invalid template /
        LLM unavailable, silently falls back to `/builder/start` shape.
        """
        from fastapi.responses import JSONResponse
        from kernel.builder.extractor import extract_spec

        body = await request.json()
        text = (body.get("request") or "").strip()
        if not text:
            return JSONResponse({"error": "request must be non-empty"}, status_code=400)

        try:
            return extract_spec(
                request=text,
                session_store=request.app.state.builder_flow._store,
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            logger.exception("/builder/extract failed")
            return JSONResponse({"error": str(e)}, status_code=500)
```

(`request.app.state.builder_flow._store` reuses the same SessionStore the existing `/builder/start` writes to, so a session created by `/extract` is consumable by `/answer` and `/deploy`.)

- [ ] **Step 4: Run all builder endpoint tests, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_builder_endpoints.py -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_builder_endpoints.py
git commit -m "feat(builder): POST /builder/extract — A4 fast-path endpoint"
```

---

## Chunk 3: Backend STT endpoint — `/voice/transcribe` + F5 prewarm

**Why third:** Frontend Day 4 (audio capture) needs this endpoint live. Independent of Chunk 2.

### Task 7: Port the i16 LE PCM decode + scipy resample logic into a reusable helper

**Files:**
- Create: `kernel/voice/transcribe_helper.py`
- Create: `tests/kernel/voice/test_transcribe_helper.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/kernel/voice/test_transcribe_helper.py
"""Helper that decodes base64 i16 LE PCM and resamples to 16 kHz.

Mirrors `kernel.workers.tts_worker._handle_stt_transcribe` lines
143-199, extracted so the new HTTP endpoint can call it without
crossing a subprocess boundary.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

from kernel.voice.transcribe_helper import decode_and_resample


def _make_audio_b64(samples_i16: np.ndarray) -> str:
    return base64.b64encode(samples_i16.astype("<i2").tobytes()).decode("ascii")


def test_decode_passthrough_at_16khz() -> None:
    samples = np.array([0, 1000, -1000, 0, 32767, -32768], dtype="<i2")
    out, sr = decode_and_resample(_make_audio_b64(samples), sample_rate=16000)
    assert sr == 16000
    assert out.dtype == np.float32
    assert len(out) == len(samples)
    np.testing.assert_allclose(out[1], 1000 / 32768.0, atol=1e-4)


def test_decode_resamples_48khz_to_16khz() -> None:
    samples = np.zeros(4800, dtype="<i2")  # 100ms at 48 kHz
    samples[::3] = 1000  # tone-ish
    out, sr = decode_and_resample(_make_audio_b64(samples), sample_rate=48000)
    assert sr == 16000
    # 4800 in @ 48k → 1600 out @ 16k (3:1 ratio)
    assert abs(len(out) - 1600) <= 5  # resample_poly polyphase tolerance
    assert out.dtype == np.float32


def test_decode_rejects_odd_byte_length() -> None:
    bad = base64.b64encode(b"\x01\x02\x03").decode("ascii")  # 3 bytes — not divisible by 2
    with pytest.raises(ValueError, match="not divisible by 2"):
        decode_and_resample(bad, sample_rate=16000)
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/voice/test_transcribe_helper.py -v`

Expected: `ModuleNotFoundError: No module named 'kernel.voice.transcribe_helper'`.

- [ ] **Step 3: Implement the helper**

Create `kernel/voice/transcribe_helper.py`:

```python
"""Audio decode + resample helper for /voice/transcribe.

Ports the framing logic from `kernel.workers.tts_worker._handle_stt_transcribe`
so the FastAPI endpoint can call SpeechToText directly without spawning
a bridge subprocess.
"""

from __future__ import annotations

import base64

import numpy as np
from scipy.signal import resample_poly


_TARGET_SR = 16000


def decode_and_resample(audio_b64: str, sample_rate: int) -> tuple[np.ndarray, int]:
    """Decode base64 i16 LE PCM, return float32 mono at 16 kHz.

    Args:
        audio_b64: Base64-encoded raw i16 little-endian PCM samples.
        sample_rate: Sample rate of the decoded samples.

    Returns:
        ``(audio_f32, target_sr)`` — float32 in [-1, 1] at 16 kHz mono.

    Raises:
        ValueError: If the decoded byte count is odd (i16 LE is
            inherently 2 bytes per sample).
    """
    raw = base64.b64decode(audio_b64)
    if len(raw) % 2 != 0:
        raise ValueError(
            f"audio_b64 length {len(raw)} not divisible by 2 (expected i16 LE)"
        )
    samples_i16 = np.frombuffer(raw, dtype="<i2")
    audio_f32 = samples_i16.astype(np.float32) / 32768.0

    if sample_rate != _TARGET_SR:
        from math import gcd

        g = gcd(sample_rate, _TARGET_SR)
        up = _TARGET_SR // g
        down = sample_rate // g
        audio_f32 = resample_poly(audio_f32, up, down).astype(np.float32)

    return audio_f32, _TARGET_SR
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/voice/test_transcribe_helper.py -v`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/voice/transcribe_helper.py tests/kernel/voice/test_transcribe_helper.py
git commit -m "feat(voice): decode_and_resample helper for /voice/transcribe"
```

---

### Task 8: Add `POST /voice/transcribe` endpoint

**Files:**
- Modify: `kernel/main.py` (near the existing `/voice/*` blocks)
- Create: `tests/kernel/test_voice_transcribe_endpoint.py`

- [ ] **Step 1: Write failing endpoint tests**

```python
# tests/kernel/test_voice_transcribe_endpoint.py
"""Default-suite tests for /voice/transcribe.

HTTP-shell behaviour only: validates request schema, auth-free 4xx
mapping, response shape against a mocked SpeechToText. Real STT
integration lives behind the `ml-tests` feature gate.
"""
from __future__ import annotations

import base64
from unittest.mock import MagicMock

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from kernel.main import create_app


@pytest.fixture
async def client(monkeypatch):
    app = create_app()

    fake_stt = MagicMock()
    fake_model = MagicMock()
    fake_seg = MagicMock()
    fake_seg.text = "трекер воды"
    fake_info = MagicMock()
    fake_info.language = "ru"
    fake_model.transcribe = MagicMock(return_value=([fake_seg], fake_info))
    fake_stt._model = fake_model
    app.state.stt = fake_stt

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_audio_b64(n_samples: int = 1600) -> str:
    samples = np.zeros(n_samples, dtype="<i2")
    return base64.b64encode(samples.tobytes()).decode("ascii")


async def test_transcribe_returns_text(client):
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": _make_audio_b64(), "sample_rate": 16000, "language": "ru"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["text"] == "трекер воды"
    assert data["language"] == "ru"
    assert data["duration_ms"] >= 0


async def test_transcribe_rejects_missing_audio(client):
    r = await client.post("/voice/transcribe", json={"sample_rate": 16000})
    assert r.status_code == 400
    assert "audio_b64" in r.json()["error"].lower()


async def test_transcribe_rejects_odd_byte_length(client):
    bad = base64.b64encode(b"\x01\x02\x03").decode("ascii")
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": bad, "sample_rate": 16000},
    )
    assert r.status_code == 400
    assert "divisible by 2" in r.json()["error"]


async def test_transcribe_resamples_48khz(client):
    """The endpoint forwards `sample_rate` to the helper; resample is
    transparent. We pass `language="ru"` so the test hits the same
    mocked `_model.transcribe` branch as the other tests (otherwise
    it falls through to `stt.transcribe()` which the fixture doesn't
    mock and FastAPI's JSON serialiser chokes on the MagicMock result).
    """
    r = await client.post(
        "/voice/transcribe",
        json={"audio_b64": _make_audio_b64(4800), "sample_rate": 48000, "language": "ru"},
    )
    assert r.status_code == 200
```

- [ ] **Step 2: Run, verify failure**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_voice_transcribe_endpoint.py -v`

Expected: 404.

- [ ] **Step 3: Implement the endpoint with a lazy-init helper for `app.state.stt`**

The Phase 3 in-process pipeline currently keeps `SpeechToText` as a private attribute (`pipeline._stt`) and never attaches it to `app.state`. With `voice.engine: rust` (now the default after the Phase 3 cutover), the Python pipeline isn't even constructed. So we cannot rely on existing init — the endpoint must initialise / cache the model itself on first request.

Add a lazy-init helper to `kernel/voice/transcribe_helper.py` (extends the file from Task 7):

```python
# append to kernel/voice/transcribe_helper.py

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kernel.voice.stt import SpeechToText

_stt_lock = threading.Lock()


def get_or_create_stt(app_state) -> "SpeechToText":
    """Return the cached SpeechToText, instantiating on first use.

    Cached on `app_state.stt` so the Tauri build keeps a single model
    in memory across requests. Mirrors `tts_worker._ensure_stt()` so
    the bridge-process and the FastAPI endpoint converge on the same
    initialisation contract.

    Thread-safe via a module lock — first request wins; subsequent
    requests reuse the cached instance.
    """
    existing = getattr(app_state, "stt", None)
    if existing is not None:
        return existing

    with _stt_lock:
        existing = getattr(app_state, "stt", None)
        if existing is not None:
            return existing
        from kernel.voice.stt import SpeechToText

        stt = SpeechToText()
        app_state.stt = stt
        return stt
```

In `kernel/main.py`, find the `@app.get("/health/tts")` block (around line 1429). Insert a new endpoint above it:

```python
    @app.post("/voice/transcribe")
    async def voice_transcribe(request: Request) -> Any:
        """One-shot STT for the voice-builder pilot.

        Bypasses the orchestrated wake-word pipeline — uses an
        in-process SpeechToText (lazy-instantiated on first request,
        cached on app.state.stt) and reuses the i16 LE PCM decode +
        scipy resample logic from the bridge worker.
        """
        from fastapi.responses import JSONResponse
        import asyncio
        import time

        from kernel.voice.transcribe_helper import (
            decode_and_resample, get_or_create_stt,
        )

        body = await request.json()
        audio_b64 = body.get("audio_b64")
        if not audio_b64:
            return JSONResponse(
                {"error": "audio_b64 required"}, status_code=400
            )
        sample_rate = int(body.get("sample_rate", 16000))
        language = body.get("language")

        try:
            audio_f32, target_sr = decode_and_resample(audio_b64, sample_rate)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

        try:
            stt = await asyncio.to_thread(get_or_create_stt, request.app.state)
        except Exception as e:
            logger.exception("/voice/transcribe failed to init SpeechToText")
            return JSONResponse({"error": str(e)}, status_code=500)

        t0 = time.perf_counter()
        try:
            if language and stt._model is not None:
                segments, info = await asyncio.to_thread(
                    stt._model.transcribe,
                    audio_f32,
                    beam_size=5,
                    language=language,
                    vad_filter=True,
                )
                text = " ".join(s.text.strip() for s in segments).strip()
                detected_language = info.language
            else:
                result = await asyncio.to_thread(
                    stt.transcribe, audio_f32, sample_rate=target_sr
                )
                text = result.text
                detected_language = result.language
        except Exception as e:
            logger.exception("/voice/transcribe failed")
            return JSONResponse({"error": str(e)}, status_code=500)

        return {
            "text": text,
            "language": detected_language,
            "duration_ms": int((time.perf_counter() - t0) * 1000),
        }
```

The test fixture sets `app.state.stt` directly, bypassing `get_or_create_stt`'s lock-protected init — that's intentional, the helper short-circuits when the cache is already populated.

- [ ] **Step 4: Run, verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/test_voice_transcribe_endpoint.py -v`

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_voice_transcribe_endpoint.py
git commit -m "feat(voice): POST /voice/transcribe (in-process Whisper, no bridge)"
```

---

### Task 9: F5 prewarm in the existing FastAPI `lifespan` context manager

**Files:**
- Modify: `kernel/main.py` (the `@asynccontextmanager async def lifespan(app: FastAPI)` around line 264)

`kernel/main.py` already uses a `lifespan` context manager wired via `FastAPI(..., lifespan=lifespan)` — adding `@app.on_event("startup")` would work but is deprecated and inconsistent with the codebase's chosen pattern. We fold the prewarm into the existing `lifespan` startup section.

- [ ] **Step 1: Locate the lifespan startup section**

Run: `grep -n "asynccontextmanager\|^async def lifespan" kernel/main.py | head -5`

You should find one `lifespan` definition (around line 264) using `@asynccontextmanager`. The startup work runs before the `yield` statement. Find the place where the voice pipeline / event bus / runtime are initialised.

- [ ] **Step 2: Add the prewarm at the end of the startup section, before `yield`**

Inside the `lifespan` body, after the existing `app.state.*` assignments and before `yield`:

```python
    # F5-TTS prewarm — load models eagerly so the first /tts/speak (the
    # voice-builder's first wizard question) doesn't pay the ~5s cold-
    # load cost at the worst possible moment. Best-effort: failures here
    # don't abort startup, the on-demand load path in /tts/speak still
    # serves as fallback.
    try:
        import asyncio
        from kernel.voice.tts_router import is_loaded, load_models

        if not is_loaded():
            logger.info("TTS prewarm: loading F5 models...")
            await asyncio.to_thread(load_models)
            logger.info("TTS prewarm: ready")
    except Exception as e:
        logger.warning("TTS prewarm failed (non-fatal): %s", e)
```

If `kernel/main.py` does NOT have a `lifespan` (older FastAPI codebases), fall back to:

```python
    @app.on_event("startup")
    async def _prewarm_tts() -> None:
        # ... same body as above ...
```

— but the grep above will tell you which path applies.

- [ ] **Step 3: Smoke-test that startup still completes**

Run: `.venv/Scripts/python.exe -m pytest tests/kernel/ -v --timeout 30`

Expected: all builder, voice, and main-app tests still pass within timeout. (The hook fires once per process; tests reusing `create_app()` will see it run once per fixture scope.)

- [ ] **Step 4: Commit**

```bash
git add kernel/main.py
git commit -m "feat(voice): prewarm F5-TTS at FastAPI startup (kills first-question cold-load)"
```

---

## Chunk 4: Frontend foundation — extend `useBuilderStore` + `builderApi`

**Why fourth:** Backend is live as of Chunk 3. Frontend can now extend the store / API client and have working integration tests immediately.

### Task 10: Extend `BuilderPhase` enum + state machine in `useBuilderStore`

**Files:**
- Modify: `ui/src/stores/builder.ts`
- Create: `ui/src/stores/__tests__/builder.test.ts`

- [ ] **Step 1: Write failing store tests**

```typescript
// ui/src/stores/__tests__/builder.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useBuilderStore } from "../builder";

vi.mock("../../api/builder", () => ({
  builderApi: {
    extract: vi.fn(),
    start: vi.fn(),
    answer: vi.fn(),
    deploy: vi.fn(),
    cancel: vi.fn(),
    transcribe: vi.fn(),
    say: vi.fn(),
  },
}));

describe("useBuilderStore phases", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
  });

  it("starts in idle", () => {
    expect(useBuilderStore.getState().phase).toBe("idle");
  });

  it("transitions through listening → transcribing → extracting on submitAudio", async () => {
    const { builderApi } = await import("../../api/builder");
    (builderApi.transcribe as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: "трекер воды",
      language: "ru",
      duration_ms: 100,
    });
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: false,
      session_id: "sid1",
      step: 0,
      total_steps: 3,
      next_question: "Какая дневная цель?",
      partial_spec: { name: "treker-vody", template: "tracker", config: {} },
    });

    const phases: string[] = [];
    const unsub = useBuilderStore.subscribe((s) => phases.push(s.phase));

    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("listening");

    const fakeBlob = new Uint8Array([0, 0, 0, 0]);
    await useBuilderStore.getState().submitAudio(fakeBlob, 16000);

    unsub();
    expect(phases).toContain("transcribing");
    expect(phases).toContain("extracting");
    expect(useBuilderStore.getState().phase).toBe("asking");
    expect(useBuilderStore.getState().sessionId).toBe("sid1");
  });

  it("complete=true skips wizard and lands on previewing", async () => {
    const { builderApi } = await import("../../api/builder");
    (builderApi.transcribe as ReturnType<typeof vi.fn>).mockResolvedValue({
      text: "трекер 2 литра 2 часа в чат",
      language: "ru",
      duration_ms: 100,
    });
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: true,
      session_id: "sid2",
      spec: {
        name: "treker-vody",
        template: "tracker",
        description: "...",
        type: "skill",
        config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
      },
    });

    const fakeBlob = new Uint8Array([0, 0, 0, 0]);
    await useBuilderStore.getState().submitAudio(fakeBlob, 16000);

    expect(useBuilderStore.getState().phase).toBe("previewing");
    expect(useBuilderStore.getState().preview?.name).toBe("treker-vody");
  });

  it("tap during listening cancels back to idle", () => {
    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("listening");
    useBuilderStore.getState().tap();
    expect(useBuilderStore.getState().phase).toBe("idle");
  });
});
```

- [ ] **Step 2: Run, verify failure**

Run: `cd ui && pnpm test -- builder.test`

Expected: type errors / new actions don't exist yet.

- [ ] **Step 3: Extend the store**

Replace `ui/src/stores/builder.ts` with:

```typescript
import { create } from "zustand";
import { builderApi, type BuilderPreview } from "../api/builder";

export type BuilderPhase =
  | "idle"
  | "listening"     // mic active, capturing audio
  | "transcribing"  // audio → /voice/transcribe
  | "extracting"    // text → /builder/extract
  | "asking"        // wizard mid-flow (sub-state via askingSubState)
  | "previewing"    // A6 readback
  | "deploying"
  | "done"
  | "error";

export type AskingSubState = "tts_speaking" | "listening_for_answer";
export type PreviewSubState = "tts_speaking" | "listening_for_command";

interface BuilderState {
  phase: BuilderPhase;
  askingSubState: AskingSubState;
  previewSubState: PreviewSubState;
  sessionId: string | null;
  request: string;
  questions: string[];           // full wizard question list (needed for editField)
  question: string | null;
  step: number;
  totalSteps: number;
  preview: BuilderPreview | null;
  partialSpec: BuilderPreview | null;
  transcript: string;
  error: string | null;

  tap: () => void;
  submitAudio: (audio: Uint8Array | ArrayBuffer, sample_rate: number) => Promise<void>;
  start: (request: string) => Promise<void>;  // text-fallback path
  answer: (text: string) => Promise<void>;
  deploy: () => Promise<void>;
  cancel: () => Promise<void>;
  /** A6 voice command: "поправь интервал" → re-enter wizard at the
   *  question whose `_question_to_key` matches `field`. No-op if the
   *  field isn't recognised in the current wizard's question list. */
  editField: (field: string) => void;
  setAskingSubState: (s: AskingSubState) => void;
  setPreviewSubState: (s: PreviewSubState) => void;
  reset: () => void;
}

const _toBase64 = (audio: Uint8Array | ArrayBuffer): string => {
  const bytes = audio instanceof Uint8Array ? audio : new Uint8Array(audio);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
};

// Same Russian-keyword rules as the backend `_question_to_key` helper —
// kept in sync via a shared parametrized vitest if a third caller appears.
// For now: small enough to duplicate; correctness covered by the editField
// vitest test below.
const _questionToKey = (question: string): string => {
  const q = question.toLowerCase();
  if (q.includes("часто") || q.includes("interval")) return "interval";
  if (q.includes("цел") || q.includes("goal")) return "goal";
  if (q.includes("услов") || q.includes("trigger")) return "trigger";
  if (q.includes("уведом") || q.includes("notify") || q.includes("куда")) return "notify_channel";
  if (q.includes("url") || q.includes("сервис")) return "target";
  if (q.includes("событ") || q.includes("категор")) return "categories";
  if (q.includes("врем") || q.includes("time")) return "time_window";
  return "";
};

export const useBuilderStore = create<BuilderState>((set, get) => ({
  phase: "idle",
  askingSubState: "tts_speaking",
  previewSubState: "tts_speaking",
  sessionId: null,
  request: "",
  questions: [],
  question: null,
  step: 0,
  totalSteps: 0,
  preview: null,
  partialSpec: null,
  transcript: "",
  error: null,

  tap: () => {
    const { phase } = get();
    if (phase === "idle") set({ phase: "listening", error: null });
    else if (phase === "listening") set({ phase: "idle" });
    // Other phases: tap is a no-op (orb is disabled in UI).
  },

  editField: (field) => {
    const { questions } = get();
    const idx = questions.findIndex((q) => _questionToKey(q) === field);
    if (idx < 0) return;  // unknown field — silently no-op (UI shows preview unchanged)
    set({
      step: idx,
      question: questions[idx],
      phase: "asking",
      askingSubState: "tts_speaking",
      preview: null,  // wizard re-fills the slot
    });
  },

  submitAudio: async (audio, sample_rate) => {
    set({ phase: "transcribing" });
    try {
      const audio_b64 = _toBase64(audio);
      const stt = await builderApi.transcribe(audio_b64, sample_rate, "ru");
      set({ transcript: stt.text, phase: "extracting", request: stt.text });

      const result = await builderApi.extract(stt.text, "ru");
      if (result.complete) {
        set({
          sessionId: result.session_id,
          preview: result.spec,
          questions: [],
          phase: "previewing",
          previewSubState: "tts_speaking",
        });
      } else {
        // Server returns `next_question` plus `step` and `total_steps`. To
        // support `editField` we also need the full question list; the
        // extractor doesn't surface it explicitly, so reconstruct it via a
        // GET to /builder/answer? — actually no, easier: extractor's
        // BuilderSession holds session.questions, but the HTTP shape only
        // includes next_question. Solution: extractor.py also returns a
        // `questions: string[]` field in the partial response (extend the
        // contract — see Chunk 2 update note below). For complete=true we
        // don't need it (no wizard to re-enter).
        set({
          sessionId: result.session_id,
          step: result.step,
          totalSteps: result.total_steps,
          questions: result.questions,
          question: result.next_question,
          partialSpec: result.partial_spec,
          phase: "asking",
          askingSubState: "tts_speaking",
        });
      }
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  start: async (request) => {
    // Text-fallback path (StarterExamples or "печатать вместо голоса").
    set({ phase: "extracting", request, error: null });
    try {
      const result = await builderApi.extract(request, "ru");
      if (result.complete) {
        set({
          sessionId: result.session_id,
          preview: result.spec,
          questions: [],
          phase: "previewing",
          previewSubState: "tts_speaking",
        });
      } else {
        set({
          sessionId: result.session_id,
          step: result.step,
          totalSteps: result.total_steps,
          questions: result.questions,
          question: result.next_question,
          partialSpec: result.partial_spec,
          phase: "asking",
          askingSubState: "tts_speaking",
        });
      }
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
        set({
          preview: r.preview,
          phase: "previewing",
          askingSubState: "tts_speaking",
          question: null,
        });
      } else {
        set({
          question: r.question ?? null,
          step: r.step ?? get().step + 1,
          askingSubState: "tts_speaking",
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

  setAskingSubState: (s) => set({ askingSubState: s }),
  setPreviewSubState: (s) => set({ previewSubState: s }),

  reset: () =>
    set({
      phase: "idle",
      askingSubState: "tts_speaking",
      previewSubState: "tts_speaking",
      sessionId: null,
      request: "",
      questions: [],
      question: null,
      step: 0,
      totalSteps: 0,
      preview: null,
      partialSpec: null,
      transcript: "",
      error: null,
    }),
}));
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd ui && pnpm test -- builder.test`

Expected: 4 passed.

- [ ] **Step 5: Run full UI test + tsc**

Run: `cd ui && pnpm test && npx tsc --noEmit`

Expected: all green; tsc exit 0. Existing `BuilderPanel` may now have type errors against the renamed phases — fix in Chunk 6 when we replace it. For now, verify tsc errors are LIMITED to `BuilderPanel.tsx` / its sub-components (not unrelated files).

If unrelated files break, revert and investigate.

- [ ] **Step 6: Commit**

```bash
git add ui/src/stores/builder.ts ui/src/stores/__tests__/builder.test.ts
git commit -m "feat(ui): extend useBuilderStore with voice phases + state machine"
```

---

### Task 11: Extend `builderApi` with `transcribe`, `extract`, `say`

**Files:**
- Modify: `ui/src/api/builder.ts`

- [ ] **Step 1: Update the API client**

Replace `ui/src/api/builder.ts` with:

```typescript
// ui/src/api/builder.ts
import { resolveApiUrl } from "./endpoints";

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

export type ExtractResponse =
  | { complete: true; session_id: string; spec: BuilderPreview }
  | {
      complete: false;
      session_id: string;
      step: number;
      total_steps: number;
      /** Full wizard question list — needed for editField (jump-to-field). */
      questions: string[];
      next_question: string;
      partial_spec: BuilderPreview;
    };

export interface TranscribeResponse {
  text: string;
  language: string;
  duration_ms: number;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(resolveApiUrl(path, "POST"), {
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
  // existing
  start: (request: string) =>
    postJson<BuilderStartResponse>("/builder/start", { request }),
  answer: (session_id: string, answer: string) =>
    postJson<BuilderAnswerResponse>("/builder/answer", { session_id, answer }),
  deploy: (session_id: string) =>
    postJson<{ status: string; name?: string }>("/builder/deploy", { session_id }),
  cancel: (session_id: string) =>
    postJson<{ status: string }>("/builder/cancel", { session_id }),

  // new — A4 fast-path
  extract: (request: string, language: string = "ru") =>
    postJson<ExtractResponse>("/builder/extract", { request, language }),

  // new — STT
  transcribe: (audio_b64: string, sample_rate: number, language: string = "ru") =>
    postJson<TranscribeResponse>("/voice/transcribe", { audio_b64, sample_rate, language }),

  // new — TTS playback (returns once audio finishes; duration is server-side)
  say: (text: string, language: string = "ru") =>
    postJson<{ status: string; duration: number }>("/tts/speak", { text, language }),
};
```

- [ ] **Step 2: Run typecheck + tests**

Run: `cd ui && npx tsc --noEmit && pnpm test -- builder.test`

Expected: tsc exit 0; existing tests green; new store tests still green (they mock builderApi).

- [ ] **Step 3: Commit**

```bash
git add ui/src/api/builder.ts
git commit -m "feat(ui): builderApi adds extract, transcribe, say"
```

---

## Chunk 5: Frontend audio + orb — `VoiceOrb.tsx` + browser capture

**Why fifth:** Audio capture is independent of the screen layout; can be developed and unit-tested in isolation. Lands as a working component before the screen consumes it.

### Task 12: Create `useAudioCapture` hook (MediaRecorder for blob + AnalyserNode for live VAD frames + Float32→Int16)

**Files:**
- Create: `ui/src/components/VoiceBuilder/useAudioCapture.ts`
- Create: `ui/src/components/VoiceBuilder/__tests__/useAudioCapture.test.ts`

**Why two audio paths:** the pilot needs both the **complete utterance blob** (sent to `/voice/transcribe` after the user stops talking) AND **live frame samples during recording** so a VAD can detect 1.5s of silence. `MediaRecorder` only gives the blob on `stop()`. So we tee the live `MediaStream` into both: (a) `MediaRecorder` for the eventual blob, and (b) an `AnalyserNode` for `setInterval`-polled Float32 frames consumed by the VAD via the `onFrame` callback. Without this, recording never auto-stops and the user has to tap the orb manually — defeating the spec's auto-VAD behaviour.

- [ ] **Step 1: Write the failing hook test**

```typescript
// ui/src/components/VoiceBuilder/__tests__/useAudioCapture.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useAudioCapture } from "../useAudioCapture";

describe("useAudioCapture", () => {
  let mediaStream: MediaStream;

  beforeEach(() => {
    mediaStream = { getTracks: () => [{ stop: vi.fn() }] } as unknown as MediaStream;

    (globalThis as any).navigator = (globalThis as any).navigator || {};
    (globalThis.navigator as any).mediaDevices = {
      getUserMedia: vi.fn().mockResolvedValue(mediaStream),
    };

    class FakeMediaRecorder {
      static isTypeSupported = () => true;
      ondataavailable: ((e: { data: Blob }) => void) | null = null;
      onstop: (() => void) | null = null;
      state = "inactive";
      start() { this.state = "recording"; }
      stop() {
        this.state = "inactive";
        const blob = new Blob([new Uint8Array([0, 0, 0, 0])], { type: "audio/webm" });
        this.ondataavailable?.({ data: blob });
        this.onstop?.();
      }
    }
    (globalThis as any).MediaRecorder = FakeMediaRecorder;

    class FakeAnalyser {
      fftSize = 1024;
      getFloatTimeDomainData(target: Float32Array) {
        // Fill with zeros — silent. Test-specific cases override.
        target.fill(0);
      }
    }

    class FakeAudioContext {
      sampleRate = 48000;
      decodeAudioData = vi.fn().mockResolvedValue({
        getChannelData: () => new Float32Array(1600),
        sampleRate: 48000,
        length: 1600,
      });
      createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
      createAnalyser = vi.fn(() => new FakeAnalyser());
      close = vi.fn();
    }
    (globalThis as any).AudioContext = FakeAudioContext;
    (globalThis as any).__FakeAnalyser = FakeAnalyser;
  });

  afterEach(() => {
    delete (globalThis as any).MediaRecorder;
    delete (globalThis as any).AudioContext;
    delete (globalThis as any).__FakeAnalyser;
    vi.useRealTimers();
  });

  it("start() begins capture; stop() yields i16 PCM bytes + sample rate", async () => {
    const { result } = renderHook(() => useAudioCapture());

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.isRecording).toBe(true);

    let captured: { audio: Uint8Array; sample_rate: number } | null = null;
    await act(async () => {
      captured = await result.current.stop();
    });

    expect(captured).not.toBeNull();
    expect(captured!.sample_rate).toBe(48000);
    // 1600 Float32 samples → 1600 i16 samples → 3200 bytes
    expect(captured!.audio.length).toBe(3200);
  });

  it("onFrame is invoked every 50ms during recording", async () => {
    vi.useFakeTimers();
    const onFrame = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onFrame }));

    await act(async () => {
      await result.current.start();
    });

    act(() => {
      vi.advanceTimersByTime(160);  // ≥3 polling ticks at 50ms
    });
    expect(onFrame.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(onFrame.mock.calls[0][0]).toBeInstanceOf(Float32Array);

    await act(async () => {
      await result.current.stop();
    });

    const callsBeforeStop = onFrame.mock.calls.length;
    act(() => {
      vi.advanceTimersByTime(200);
    });
    // No further frames after stop().
    expect(onFrame.mock.calls.length).toBe(callsBeforeStop);
  });

  it("permission denied surfaces as a structured error", async () => {
    (globalThis.navigator as any).mediaDevices.getUserMedia = vi
      .fn()
      .mockRejectedValue(new DOMException("denied", "NotAllowedError"));

    const { result } = renderHook(() => useAudioCapture());

    await expect(
      act(async () => {
        await result.current.start();
      }),
    ).rejects.toThrow(/NotAllowedError|denied/);
  });
});
```

**Verify the Vitest environment supports `DOMException`** before adding the third test:
```bash
grep -E "environment|jsdom|happy-dom" ui/vite.config.ts ui/vitest.config.ts 2>/dev/null
```
If neither `jsdom` nor `happy-dom` is configured, add `environment: "jsdom"` to `vitest.config.ts` first or skip the permission-denied test (gate behind `it.skipIf(!globalThis.DOMException)`).

- [ ] **Step 2: Run, verify failure**

Run: `cd ui && pnpm test -- useAudioCapture`

Expected: `Cannot find module '../useAudioCapture'`.

- [ ] **Step 3: Implement the hook**

Create `ui/src/components/VoiceBuilder/useAudioCapture.ts`:

```typescript
import { useCallback, useRef, useState } from "react";

interface UseAudioCaptureOptions {
  /**
   * Called every ~50ms during recording with the latest Float32 frame
   * from the AnalyserNode (typically `fftSize` samples = 1024). Use for
   * VAD or live visualisations. Optional — the hook also works as a
   * pure record-and-blob primitive without it.
   */
  onFrame?: (frame: Float32Array) => void;
}

interface UseAudioCaptureResult {
  start: () => Promise<void>;
  stop: () => Promise<{ audio: Uint8Array; sample_rate: number } | null>;
  isRecording: boolean;
}

const POLL_MS = 50;
const FFT_SIZE = 1024;

/**
 * Browser audio capture for the voice-builder pilot.
 *
 * Two parallel paths off one MediaStream:
 * - MediaRecorder (webm/opus) → on stop(), decode to Float32 → Int16 LE
 *   → return as Uint8Array. This is what we send to /voice/transcribe.
 * - AnalyserNode polled every 50ms → onFrame(Float32) callback. This
 *   feeds the RMS-VAD so the pilot can auto-stop on silence without
 *   waiting for the recorder's blob.
 *
 * The Int16 conversion is symmetric (multiply by 32767 in both
 * directions) to match the bridge worker's symmetric divide-by-32768
 * decode in tts_worker.py:161 — same convention round-trip.
 */
export function useAudioCapture(opts: UseAudioCaptureOptions = {}): UseAudioCaptureResult {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const pollerRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const onFrameRef = useRef(opts.onFrame);
  onFrameRef.current = opts.onFrame;
  const [isRecording, setIsRecording] = useState(false);

  const start = useCallback(async () => {
    chunksRef.current = [];
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    streamRef.current = stream;

    // Live frame tap for VAD.
    const audioCtx = new AudioContext();
    audioCtxRef.current = audioCtx;
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = FFT_SIZE;
    source.connect(analyser);
    analyserRef.current = analyser;

    const buf = new Float32Array(analyser.fftSize);
    pollerRef.current = window.setInterval(() => {
      analyserRef.current?.getFloatTimeDomainData(buf);
      onFrameRef.current?.(buf);
    }, POLL_MS);

    // Blob path for the eventual /voice/transcribe payload.
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.start();
    recorderRef.current = recorder;
    setIsRecording(true);
  }, []);

  const stop = useCallback(async () => {
    if (pollerRef.current !== null) {
      window.clearInterval(pollerRef.current);
      pollerRef.current = null;
    }

    const recorder = recorderRef.current;
    if (!recorder) {
      audioCtxRef.current?.close();
      audioCtxRef.current = null;
      analyserRef.current = null;
      return null;
    }

    const stopped = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.stop();
    await stopped;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close();
    audioCtxRef.current = null;
    analyserRef.current = null;
    setIsRecording(false);

    const webmBlob = new Blob(chunksRef.current, { type: "audio/webm" });
    const arrayBuffer = await webmBlob.arrayBuffer();
    const decodeCtx = new AudioContext();
    const decoded = await decodeCtx.decodeAudioData(arrayBuffer);
    const sample_rate = decoded.sampleRate;
    const float32 = decoded.getChannelData(0);
    decodeCtx.close();

    // Float32 [-1, 1] → Int16 LE — symmetric scaling to match
    // tts_worker.py:161 which divides by 32768.0 in both directions.
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const clamped = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = Math.round(clamped * 32767);
    }
    const audio = new Uint8Array(int16.buffer);

    recorderRef.current = null;
    streamRef.current = null;
    return { audio, sample_rate };
  }, []);

  return { start, stop, isRecording };
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd ui && pnpm test -- useAudioCapture`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/useAudioCapture.ts ui/src/components/VoiceBuilder/__tests__/useAudioCapture.test.ts
git commit -m "feat(ui): useAudioCapture (MediaRecorder blob + AnalyserNode live frames)"
```

---

### Task 13: Create `useRmsVad` hook (1.5s silence detection)

**Files:**
- Create: `ui/src/components/VoiceBuilder/useRmsVad.ts`
- Create: `ui/src/components/VoiceBuilder/__tests__/useRmsVad.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// ui/src/components/VoiceBuilder/__tests__/useRmsVad.test.ts
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useRmsVad } from "../useRmsVad";

describe("useRmsVad", () => {
  it("triggers onSilence after the configured silence duration of low RMS", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();

    const { result } = renderHook(() =>
      useRmsVad({
        threshold: 0.01,
        silenceMs: 1500,
        onSilence,
      }),
    );

    // Push 200 frames of silence (RMS=0). At 50ms each → 10s wall.
    act(() => {
      for (let i = 0; i < 40; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
    });

    expect(onSilence).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("resets the silence timer on a loud frame", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();

    const { result } = renderHook(() =>
      useRmsVad({ threshold: 0.01, silenceMs: 1500, onSilence }),
    );

    act(() => {
      for (let i = 0; i < 20; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
      // 1s of silence so far — under threshold
      expect(onSilence).not.toHaveBeenCalled();

      // Loud frame resets
      result.current.feed(new Float32Array(800).fill(0.5));
      vi.advanceTimersByTime(50);

      // More silence — needs a full 1500ms again
      for (let i = 0; i < 25; i++) {
        result.current.feed(new Float32Array(800).fill(0));
        vi.advanceTimersByTime(50);
      }
    });

    expect(onSilence).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run, verify failure**

Run: `cd ui && pnpm test -- useRmsVad`

Expected: cannot find module.

- [ ] **Step 3: Implement the hook**

Create `ui/src/components/VoiceBuilder/useRmsVad.ts`:

```typescript
import { useCallback, useRef } from "react";

interface UseRmsVadOptions {
  /** Below this RMS, frames count as silence (0–1 range). Default 0.01. */
  threshold?: number;
  /** Continuous silence for this many ms triggers `onSilence`. Default 1500. */
  silenceMs?: number;
  /** Fired exactly once per silence transition. */
  onSilence: () => void;
}

interface UseRmsVadResult {
  /** Feed a chunk of float32 mono samples. Call as often as audio arrives. */
  feed: (chunk: Float32Array) => void;
  reset: () => void;
}

/**
 * RMS-threshold VAD with a silence-duration timer. Stateless wrt audio
 * (no buffer); the consumer feeds chunks as they're produced and the
 * hook tracks how long the recent RMS has been below threshold.
 */
export function useRmsVad({
  threshold = 0.01,
  silenceMs = 1500,
  onSilence,
}: UseRmsVadOptions): UseRmsVadResult {
  const silenceStartRef = useRef<number | null>(null);
  const firedRef = useRef(false);

  const feed = useCallback(
    (chunk: Float32Array) => {
      let sumSq = 0;
      for (let i = 0; i < chunk.length; i++) sumSq += chunk[i] * chunk[i];
      const rms = Math.sqrt(sumSq / Math.max(1, chunk.length));

      const now = Date.now();
      if (rms < threshold) {
        if (silenceStartRef.current === null) silenceStartRef.current = now;
        if (
          !firedRef.current &&
          now - silenceStartRef.current >= silenceMs
        ) {
          firedRef.current = true;
          onSilence();
        }
      } else {
        silenceStartRef.current = null;
        firedRef.current = false;
      }
    },
    [threshold, silenceMs, onSilence],
  );

  const reset = useCallback(() => {
    silenceStartRef.current = null;
    firedRef.current = false;
  }, []);

  return { feed, reset };
}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd ui && pnpm test -- useRmsVad`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/useRmsVad.ts ui/src/components/VoiceBuilder/__tests__/useRmsVad.test.ts
git commit -m "feat(ui): useRmsVad hook (1.5s silence detection)"
```

---

### Task 14: Create `VoiceOrb.tsx` component

**Files:**
- Create: `ui/src/components/VoiceBuilder/VoiceOrb.tsx`
- Create: `ui/src/components/VoiceBuilder/__tests__/VoiceOrb.test.tsx`

- [ ] **Step 1: Write the failing component test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/VoiceOrb.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { VoiceOrb } from "../VoiceOrb";

describe("VoiceOrb", () => {
  it("renders the idle state with a ring", () => {
    render(<VoiceOrb state="idle" onTap={() => {}} />);
    expect(screen.getByRole("button", { name: /микрофон/i })).toBeInTheDocument();
  });

  it("calls onTap when clicked in idle / listening", () => {
    const tap = vi.fn();
    const { rerender } = render(<VoiceOrb state="idle" onTap={tap} />);
    fireEvent.click(screen.getByRole("button"));
    expect(tap).toHaveBeenCalledTimes(1);

    rerender(<VoiceOrb state="listening" onTap={tap} />);
    fireEvent.click(screen.getByRole("button"));
    expect(tap).toHaveBeenCalledTimes(2);
  });

  it("disables tap during processing", () => {
    const tap = vi.fn();
    render(<VoiceOrb state="processing" onTap={tap} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
    fireEvent.click(btn);
    expect(tap).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, verify failure**

Run: `cd ui && pnpm test -- VoiceOrb`

Expected: cannot find module.

- [ ] **Step 3: Implement the component**

Create `ui/src/components/VoiceBuilder/VoiceOrb.tsx`:

```tsx
import { Mic, Loader2 } from "lucide-react";

export type VoiceOrbState = "idle" | "listening" | "processing";

interface Props {
  state: VoiceOrbState;
  onTap: () => void;
}

export function VoiceOrb({ state, onTap }: Props) {
  const disabled = state === "processing";
  const icon =
    state === "processing" ? (
      <Loader2 size={32} className="animate-spin" />
    ) : (
      <Mic size={32} />
    );
  return (
    <button
      type="button"
      aria-label="Микрофон"
      disabled={disabled}
      onClick={onTap}
      className="voice-orb"
      data-state={state}
      style={{
        width: 96,
        height: 96,
        borderRadius: "50%",
        border: "2px solid var(--j-cyan)",
        background:
          state === "listening"
            ? "rgba(0,224,255,0.18)"
            : "rgba(0,224,255,0.06)",
        boxShadow:
          state === "listening"
            ? "0 0 24px rgba(0,224,255,0.6)"
            : "0 0 8px rgba(0,224,255,0.2)",
        color: "var(--j-cyan)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        cursor: disabled ? "default" : "pointer",
        transition: "box-shadow 0.2s, background 0.2s",
        animation: state === "listening" ? "pulse 1.5s infinite" : undefined,
      }}
    >
      {icon}
    </button>
  );
}
```

(`pulse` keyframe is defined globally in the design-tokens CSS; confirm with `grep -r "@keyframes pulse" ui/src` and add to `tokens/animations.css` if missing.)

- [ ] **Step 4: Run tests + tsc**

Run: `cd ui && pnpm test -- VoiceOrb && npx tsc --noEmit`

Expected: 3 passed; tsc exit 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/VoiceOrb.tsx ui/src/components/VoiceBuilder/__tests__/VoiceOrb.test.tsx
git commit -m "feat(ui): VoiceOrb component with three visual states"
```

---

## Chunk 6: Frontend screen + layout — `VoiceBuilderScreen` + L1 sub-components

**Why sixth:** All ingredients ready (store, API, audio, orb). The screen ties them together. Same chunk replaces the existing `BuilderPanel` + sub-components.

### Task 15: Create `LiveTranscript.tsx`

**Files:**
- Create: `ui/src/components/VoiceBuilder/LiveTranscript.tsx`
- Create: `ui/src/components/VoiceBuilder/__tests__/LiveTranscript.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/LiveTranscript.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveTranscript } from "../LiveTranscript";

describe("LiveTranscript", () => {
  it("renders nothing when transcript is empty", () => {
    const { container } = render(<LiveTranscript transcript="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders the transcript text", () => {
    render(<LiveTranscript transcript="трекер воды" />);
    expect(screen.getByText(/трекер воды/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, verify failure** — `cd ui && pnpm test -- LiveTranscript` → cannot find module.

- [ ] **Step 3: Implement**

```tsx
// ui/src/components/VoiceBuilder/LiveTranscript.tsx
interface Props {
  transcript: string;
}

export function LiveTranscript({ transcript }: Props) {
  if (!transcript) return null;
  return (
    <div
      className="live-transcript"
      style={{
        textAlign: "center",
        color: "var(--j-text-dim)",
        fontStyle: "italic",
        maxWidth: 480,
        margin: "12px auto",
      }}
    >
      «{transcript}»
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass** — `cd ui && pnpm test -- LiveTranscript` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/LiveTranscript.tsx ui/src/components/VoiceBuilder/__tests__/LiveTranscript.test.tsx
git commit -m "feat(ui): LiveTranscript leaf component"
```

---

### Task 16: Create `SpecCard.tsx`

**Files:**
- Create: `ui/src/components/VoiceBuilder/SpecCard.tsx`
- Create: `ui/src/components/VoiceBuilder/__tests__/SpecCard.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/SpecCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SpecCard } from "../SpecCard";
import type { BuilderPreview } from "../../../api/builder";

const _spec = (config: Record<string, unknown> = {}): BuilderPreview => ({
  name: "treker-vody",
  description: "трекер",
  type: "skill",
  template: "tracker",
  config,
});

describe("SpecCard", () => {
  it("renders empty fields muted when config is empty", () => {
    render(<SpecCard spec={_spec()} highlighted={false} />);
    expect(screen.getByText(/Тэмплейт:/)).toBeInTheDocument();
    expect(screen.getByText(/трекер/)).toBeInTheDocument();
  });

  it("highlights filled config keys", () => {
    render(
      <SpecCard
        spec={_spec({ interval: "2 часа", goal: "2 литра" })}
        highlighted={false}
      />,
    );
    expect(screen.getByText(/2 часа/)).toBeInTheDocument();
    expect(screen.getByText(/2 литра/)).toBeInTheDocument();
  });

  it("applies the highlighted style during preview", () => {
    const { container } = render(
      <SpecCard spec={_spec()} highlighted={true} />,
    );
    expect(container.firstChild).toHaveAttribute("data-highlighted", "true");
  });

  it("returns null when spec is null", () => {
    const { container } = render(<SpecCard spec={null} highlighted={false} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Run, verify failure** — cannot find module.

- [ ] **Step 3: Implement**

```tsx
// ui/src/components/VoiceBuilder/SpecCard.tsx
import type { BuilderPreview } from "../../api/builder";

interface Props {
  spec: BuilderPreview | null;
  highlighted: boolean;
}

const KEY_LABELS: Record<string, string> = {
  interval: "Интервал",
  goal: "Цель",
  notify_channel: "Уведомление",
  time_window: "Время",
  target: "URL",
  trigger: "Условие",
  categories: "Категории",
};

export function SpecCard({ spec, highlighted }: Props) {
  if (!spec) return null;
  const cfg = spec.config ?? {};
  return (
    <div
      data-highlighted={highlighted}
      style={{
        border: "1px solid var(--j-border)",
        borderRadius: 8,
        padding: 16,
        background: "rgba(0,224,255,0.03)",
        boxShadow: highlighted ? "0 0 16px rgba(0,224,255,0.4)" : "none",
        maxWidth: 360,
        margin: "0 auto",
        color: "var(--j-text)",
        transition: "box-shadow 0.3s",
      }}
    >
      <div>
        Тэмплейт: <span style={{ color: "var(--j-cyan)" }}>{spec.template ?? "-"}</span>
      </div>
      <div>
        Имя: <span style={{ color: "var(--j-cyan)" }}>{spec.name}</span>
      </div>
      {Object.entries(KEY_LABELS).map(([k, label]) => {
        const val = cfg[k];
        return (
          <div key={k}>
            {label}:{" "}
            {val ? (
              <span style={{ color: "var(--j-cyan)" }}>{String(val)}</span>
            ) : (
              <span style={{ color: "var(--j-text-dim)" }}>?</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass** — 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/SpecCard.tsx ui/src/components/VoiceBuilder/__tests__/SpecCard.test.tsx
git commit -m "feat(ui): SpecCard leaf component (filled/muted/highlighted)"
```

---

### Task 17: Create `WizardPrompt.tsx` with TTS playback

**Files:**
- Create: `ui/src/components/VoiceBuilder/WizardPrompt.tsx`
- Create: `ui/src/components/VoiceBuilder/__tests__/WizardPrompt.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/WizardPrompt.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WizardPrompt } from "../WizardPrompt";

vi.mock("../../../api/builder", () => ({
  builderApi: { say: vi.fn().mockResolvedValue({ status: "ok", duration: 1.5 }) },
}));

describe("WizardPrompt", () => {
  it("renders the question and step counter", () => {
    render(<WizardPrompt question="Какая дневная цель?" step={1} totalSteps={3} onTtsDone={() => {}} />);
    expect(screen.getByText(/Какая дневная цель/)).toBeInTheDocument();
    expect(screen.getByText(/Шаг 2 из 3/)).toBeInTheDocument();
  });

  it("calls say() on mount and onTtsDone after it resolves", async () => {
    const { builderApi } = await import("../../../api/builder");
    const done = vi.fn();
    render(<WizardPrompt question="Какая дневная цель?" step={0} totalSteps={3} onTtsDone={done} />);

    await waitFor(() => expect(builderApi.say).toHaveBeenCalledWith("Какая дневная цель?", "ru"));
    await waitFor(() => expect(done).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run, verify failure**.

- [ ] **Step 3: Implement**

```tsx
// ui/src/components/VoiceBuilder/WizardPrompt.tsx
import { useEffect } from "react";
import { builderApi } from "../../api/builder";

interface Props {
  question: string;
  step: number;
  totalSteps: number;
  onTtsDone: () => void;
}

export function WizardPrompt({ question, step, totalSteps, onTtsDone }: Props) {
  useEffect(() => {
    let cancelled = false;
    void builderApi.say(question, "ru").finally(() => {
      if (!cancelled) onTtsDone();
    });
    return () => {
      cancelled = true;
    };
  }, [question, onTtsDone]);

  return (
    <div style={{ textAlign: "center", margin: "12px auto" }}>
      <div style={{ color: "var(--j-cyan)", fontSize: 18, fontWeight: 600 }}>
        {question}
      </div>
      <div style={{ color: "var(--j-text-dim)", fontSize: 12, marginTop: 8 }}>
        Шаг {step + 1} из {totalSteps}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run, verify pass** — 2 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/WizardPrompt.tsx ui/src/components/VoiceBuilder/__tests__/WizardPrompt.test.tsx
git commit -m "feat(ui): WizardPrompt with TTS readback on mount"
```

---

### Task 18: Wire `VoiceBuilderScreen.tsx` (state machine owner)

**Files:**
- Create: `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx`
- Modify: `ui/src/App.tsx` (replace `BuilderPanel` import)
- Delete: `ui/src/components/Builder/BuilderPanel.tsx`, `BuilderProgress.tsx`, `BuilderPreview.tsx`
- Move: `ui/src/components/Builder/StarterExamples.tsx` → `ui/src/components/VoiceBuilder/StarterExamples.tsx` (kept as fallback)

- [ ] **Step 1: Move StarterExamples (no rename, just relocate)**

```bash
mv ui/src/components/Builder/StarterExamples.tsx ui/src/components/VoiceBuilder/StarterExamples.tsx
```

Adjust import paths inside the file if they break (most should be relative to new location).

- [ ] **Step 2: Create `VoiceBuilderScreen.tsx`**

```tsx
// ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx
import { useEffect, useRef, useState } from "react";
import { useBuilderStore } from "../../stores/builder";
import { VoiceOrb, type VoiceOrbState } from "./VoiceOrb";
import { LiveTranscript } from "./LiveTranscript";
import { SpecCard } from "./SpecCard";
import { WizardPrompt } from "./WizardPrompt";
import { PreviewConfirm } from "./PreviewConfirm";
import { StarterExamples } from "./StarterExamples";
import { useAudioCapture } from "./useAudioCapture";
import { useRmsVad } from "./useRmsVad";
import { parseVoiceCommand } from "./voiceCommands";  // landed in Chunk 7

export function VoiceBuilderScreen() {
  const {
    phase,
    askingSubState,
    transcript,
    question,
    step,
    totalSteps,
    preview,
    partialSpec,
    error,
    tap,
    submitAudio,
    answer,
    cancel,
    deploy,
    editField,  // landed in Chunk 7
    reset,
    setAskingSubState,
    start,
  } = useBuilderStore();

  const [showFallback, setShowFallback] = useState(false);
  const [textInput, setTextInput] = useState("");
  // Phase ref so the VAD onSilence closure (created once) reads current
  // phase without forcing the audio hook to re-create on every change.
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const askingSubStateRef = useRef(askingSubState);
  askingSubStateRef.current = askingSubState;

  // Single VAD — phase-aware dispatch in onSilence keeps the wiring
  // simple and avoids the parallel-VAD race that double-stops audio.
  const vad = useRmsVad({
    silenceMs: 1500,
    threshold: 0.01,
    onSilence: async () => {
      const captured = await audio.stop();
      if (!captured) return;
      const currentPhase = phaseRef.current;
      if (currentPhase === "listening") {
        await submitAudio(captured.audio, captured.sample_rate);
      } else if (
        currentPhase === "asking" &&
        askingSubStateRef.current === "listening_for_answer"
      ) {
        const text = await transcribeOnly(captured.audio, captured.sample_rate);
        if (!text) return;
        const cmd = parseVoiceCommand(text, { phase: "asking", knownFields: [] });
        if (cmd.intent === "cancel") void cancel();
        else if (cmd.intent === "answer") await answer(cmd.text);
      } else if (currentPhase === "previewing") {
        const text = await transcribeOnly(captured.audio, captured.sample_rate);
        if (!text) return;
        const known = preview ? Object.keys(preview.config ?? {}) : [];
        const cmd = parseVoiceCommand(text, { phase: "previewing", knownFields: known });
        if (cmd.intent === "confirm") void deploy();
        else if (cmd.intent === "cancel") void cancel();
        else if (cmd.intent === "edit") void editField(cmd.field);
      }
    },
  });

  // Audio capture wired to feed the single VAD via onFrame.
  const audio = useAudioCapture({ onFrame: vad.feed });

  // Hook the orb tap → start/stop recording.
  const handleTap = async () => {
    if (phase === "idle") {
      try {
        await audio.start();
        tap();  // store transitions to listening
      } catch (e) {
        // permission denied → fallback path
        setShowFallback(true);
      }
    } else if (phase === "listening") {
      const captured = await audio.stop();
      if (!captured) return;
      tap();  // back to idle (cancel turn)
      // intentionally NOT submitting — tap-to-cancel behaviour
    }
  };

  // Cancel paths.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void cancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cancel]);

  // Mode-switch / unmount cleanup — stop any in-flight recording so
  // the OS mic indicator doesn't stay lit when the user navigates away.
  useEffect(() => {
    return () => {
      if (audio.isRecording) {
        void audio.stop();
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Map phase → orb state
  const orbState: VoiceOrbState =
    phase === "listening" || (phase === "asking" && askingSubState === "listening_for_answer")
      ? "listening"
      : phase === "transcribing" || phase === "extracting" || phase === "deploying"
      ? "processing"
      : "idle";

  return (
    <div className="voice-builder-screen" style={{ padding: 32, textAlign: "center" }}>
      <h2 style={{ color: "var(--j-text)" }}>Создать агента</h2>

      {error && (
        <div style={{ color: "var(--j-error, #f87171)", margin: 8 }}>{error}</div>
      )}

      {phase !== "previewing" && phase !== "done" && (
        <>
          <div style={{ display: "flex", justifyContent: "center", margin: 24 }}>
            <VoiceOrb state={orbState} onTap={handleTap} />
          </div>

          <LiveTranscript transcript={transcript} />

          {phase === "asking" && question && askingSubState === "tts_speaking" && (
            <WizardPrompt
              question={question}
              step={step}
              totalSteps={totalSteps}
              onTtsDone={() => setAskingSubState("listening_for_answer")}
            />
          )}

          {(phase === "asking" || phase === "listening" || phase === "transcribing" || phase === "extracting") && (
            <SpecCard spec={partialSpec ?? null} highlighted={false} />
          )}
        </>
      )}

      {phase === "previewing" && preview && (
        <PreviewConfirm spec={preview} />
      )}

      {phase === "done" && (
        <div>
          <p style={{ color: "var(--j-cyan)", fontSize: 18 }}>
            Агент готов. Попробуй: «{preview?.name}, начни»
          </p>
          <button onClick={reset} style={{ margin: 8 }}>Создать ещё</button>
        </div>
      )}

      {/* Fallback path */}
      {phase === "idle" && (
        <div style={{ marginTop: 24 }}>
          <button
            onClick={() => setShowFallback(!showFallback)}
            style={{
              background: "none",
              border: "none",
              color: "var(--j-text-dim)",
              fontSize: 12,
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            печатать вместо голоса
          </button>
          {showFallback && (
            <div style={{ marginTop: 12 }}>
              <input
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && textInput.trim()) {
                    void start(textInput);
                    setTextInput("");
                  }
                }}
                placeholder="напр. трекер воды каждые 2 часа"
                style={{
                  padding: 8,
                  borderRadius: 4,
                  border: "1px solid var(--j-border)",
                  background: "var(--j-bg)",
                  color: "var(--j-text)",
                  width: 320,
                }}
              />
              <StarterExamples onPick={(ex: string) => setTextInput(ex)} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Helper: transcribe a captured audio blob without going through submitAudio.
async function transcribeOnly(
  audio: Uint8Array,
  sample_rate: number,
): Promise<string> {
  const { builderApi } = await import("../../api/builder");
  let bin = "";
  for (let i = 0; i < audio.length; i++) bin += String.fromCharCode(audio[i]);
  const audio_b64 = btoa(bin);
  try {
    const r = await builderApi.transcribe(audio_b64, sample_rate, "ru");
    return r.text.trim();
  } catch {
    return "";
  }
}
```

- [ ] **Step 3: Update `App.tsx`**

In `ui/src/App.tsx`:
- Replace `import { BuilderPanel } from "./components/Builder/BuilderPanel";` with `import { VoiceBuilderScreen } from "./components/VoiceBuilder/VoiceBuilderScreen";`
- Replace `{mode === "builder" && <BuilderPanel />}` with `{mode === "builder" && <VoiceBuilderScreen />}`

- [ ] **Step 4: Delete the old Builder/ folder (sources + tests, move StarterExamples test alongside source)**

First inspect what's actually there so we don't leave orphans:
```bash
ls ui/src/components/Builder/ ui/src/components/Builder/__tests__/ 2>/dev/null
```

Then remove sources + their tests, and `git mv` StarterExamples test alongside the source moved in Step 1:

```bash
git rm ui/src/components/Builder/BuilderPanel.tsx
git rm ui/src/components/Builder/BuilderProgress.tsx
git rm ui/src/components/Builder/BuilderPreview.tsx
# Tests for the removed sources go too — module-not-found otherwise breaks CI:
git rm ui/src/components/Builder/__tests__/BuilderPanel.test.tsx 2>/dev/null || true
git rm ui/src/components/Builder/__tests__/BuilderProgress.test.tsx 2>/dev/null || true
git rm ui/src/components/Builder/__tests__/BuilderPreview.test.tsx 2>/dev/null || true
# StarterExamples test follows its source (Step 1 already moved the source):
git mv ui/src/components/Builder/__tests__/StarterExamples.test.tsx \
       ui/src/components/VoiceBuilder/__tests__/StarterExamples.test.tsx 2>/dev/null || true
# Clean up empty directories:
rmdir ui/src/components/Builder/__tests__ 2>/dev/null || true
rmdir ui/src/components/Builder 2>/dev/null || true
```

If the StarterExamples test imports a relative path that broke during the move, fix the import path in the test file (was `../StarterExamples`, stays `../StarterExamples` if both moved together — but verify).

- [ ] **Step 5: Run typecheck + tests**

Run: `cd ui && npx tsc --noEmit && pnpm test`

Expected: tsc exit 0; all tests green. The PreviewConfirm import is the only outstanding piece — the file lands in Chunk 7 next; for now stub it temporarily:

If PreviewConfirm doesn't exist yet, create a stub at `ui/src/components/VoiceBuilder/PreviewConfirm.tsx`:

```tsx
import type { BuilderPreview } from "../../api/builder";
export function PreviewConfirm({ spec: _spec }: { spec: BuilderPreview }) {
  return <div>Preview placeholder — Chunk 7 fills this in.</div>;
}
```

- [ ] **Step 6: Commit**

```bash
git add ui/src/App.tsx ui/src/components/VoiceBuilder/ -- :^ui/src/components/Builder/
git rm ui/src/components/Builder/BuilderPanel.tsx ui/src/components/Builder/BuilderProgress.tsx ui/src/components/Builder/BuilderPreview.tsx
git commit -m "feat(ui): VoiceBuilderScreen replaces BuilderPanel + sub-components (L1 layout)"
```

---

## Chunk 7: Frontend preview — `PreviewConfirm` + voice command parser + cancel disambiguation

**Why seventh:** Final UX before deploy. Lands the A6 readback flow + the disambiguation rule that protects against false-positive cancels.

### Task 19: Create the voice command parser

**Files:**
- Create: `ui/src/components/VoiceBuilder/voiceCommands.ts`
- Create: `ui/src/components/VoiceBuilder/__tests__/voiceCommands.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// ui/src/components/VoiceBuilder/__tests__/voiceCommands.test.ts
import { describe, expect, it } from "vitest";
import { parseVoiceCommand, type VoiceContext } from "../voiceCommands";

describe("parseVoiceCommand — preview context", () => {
  const ctx: VoiceContext = { phase: "previewing", knownFields: ["interval", "goal", "notify_channel"] };

  it("'да' → confirm", () => {
    expect(parseVoiceCommand("да", ctx)).toEqual({ intent: "confirm" });
  });
  it("'давай ставь' → confirm (token at start)", () => {
    expect(parseVoiceCommand("давай ставь", ctx)).toEqual({ intent: "confirm" });
  });
  it("'нет, отмена' → cancel (token at start)", () => {
    expect(parseVoiceCommand("нет, отмена", ctx)).toEqual({ intent: "cancel" });
  });
  it("'не надо отменять, продолжай' → no match (cancel keyword in middle)", () => {
    expect(parseVoiceCommand("не надо отменять, продолжай", ctx)).toEqual({ intent: "unknown" });
  });
  it("'поправь интервал' → edit interval", () => {
    expect(parseVoiceCommand("поправь интервал", ctx)).toEqual({ intent: "edit", field: "interval" });
  });
  it("'измени цель' → edit goal", () => {
    expect(parseVoiceCommand("измени цель", ctx)).toEqual({ intent: "edit", field: "goal" });
  });
});

describe("parseVoiceCommand — wizard answer context", () => {
  const ctx: VoiceContext = { phase: "asking", knownFields: [] };

  it("short utterance whole-match cancel triggers cancel", () => {
    expect(parseVoiceCommand("отмена", ctx)).toEqual({ intent: "cancel" });
    expect(parseVoiceCommand("не надо", ctx)).toEqual({ intent: "cancel" });
  });
  it("long utterance with cancel substring is treated as content", () => {
    expect(
      parseVoiceCommand("не надо в телеграм отмена дай голосом", ctx),
    ).toEqual({ intent: "answer", text: "не надо в телеграм отмена дай голосом" });
  });
  it("normal answer is content", () => {
    expect(parseVoiceCommand("каждые два часа", ctx)).toEqual({
      intent: "answer",
      text: "каждые два часа",
    });
  });
});
```

- [ ] **Step 2: Run, verify failure** — cannot find module.

- [ ] **Step 3: Implement**

```typescript
// ui/src/components/VoiceBuilder/voiceCommands.ts
const CONFIRM_WORDS = ["да", "давай", "ставь", "запускай", "поехали", "ок", "подтверди"];
const CANCEL_WORDS = ["отмена", "не надо", "хватит", "перестань", "стоп", "отменяй", "нет"];
const EDIT_PREFIXES = ["поправь", "измени", "переделай"];

const FIELD_KEYWORDS: Record<string, string[]> = {
  interval: ["интервал", "часто", "часов", "раз"],
  goal: ["цель", "цел"],
  notify_channel: ["уведом", "куда", "канал"],
  time_window: ["время"],
  target: ["url", "сервис", "адрес"],
  trigger: ["условие"],
  categories: ["категори", "событи"],
};

export type VoiceContext = {
  phase: "previewing" | "asking";
  knownFields: string[];
};

export type VoiceCommand =
  | { intent: "confirm" }
  | { intent: "cancel" }
  | { intent: "edit"; field: string }
  | { intent: "answer"; text: string }
  | { intent: "unknown" };

const _tokens = (s: string): string[] =>
  s
    .toLowerCase()
    .replace(/[.,!?;:«»"]/g, " ")
    .split(/\s+/)
    .filter(Boolean);

const _hasNearEdge = (toks: string[], words: string[]): boolean => {
  // Whole-token equality (not substring) prevents false positives like
  // "нетронутый" → "нет" → cancel, or "стоплосс" → "стоп" → cancel.
  const head = toks.slice(0, 3);
  const tail = toks.slice(-3);
  return words.some((w) =>
    head.includes(w) || tail.includes(w),
  );
};

export function parseVoiceCommand(text: string, ctx: VoiceContext): VoiceCommand {
  const toks = _tokens(text);
  if (toks.length === 0) return { intent: "unknown" };

  if (ctx.phase === "previewing") {
    if (_hasNearEdge(toks, CONFIRM_WORDS)) return { intent: "confirm" };
    if (_hasNearEdge(toks, CANCEL_WORDS)) return { intent: "cancel" };
    // Edit: look for "поправь <field>" / "измени <field>" / "<field>"
    for (let i = 0; i < toks.length; i++) {
      if (EDIT_PREFIXES.some((p) => toks[i].includes(p)) && i + 1 < toks.length) {
        const candidate = toks[i + 1];
        for (const [field, kws] of Object.entries(FIELD_KEYWORDS)) {
          if (
            ctx.knownFields.includes(field) &&
            kws.some((k) => candidate.includes(k))
          ) {
            return { intent: "edit", field };
          }
        }
      }
    }
    return { intent: "unknown" };
  }

  // ctx.phase === "asking" — wizard answer
  if (toks.length <= 3) {
    const joined = toks.join(" ");
    if (CANCEL_WORDS.some((c) => joined === c || joined === c.replace(" ", ""))) {
      return { intent: "cancel" };
    }
  }
  return { intent: "answer", text };
}
```

- [ ] **Step 4: Run tests, verify pass** — 9 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/voiceCommands.ts ui/src/components/VoiceBuilder/__tests__/voiceCommands.test.ts
git commit -m "feat(ui): voice command parser with disambiguation rule"
```

---

### Task 20: Create `PreviewConfirm.tsx` (replaces stub from Task 18)

**Files:**
- Modify: `ui/src/components/VoiceBuilder/PreviewConfirm.tsx`
- Create: `ui/src/components/VoiceBuilder/__tests__/PreviewConfirm.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/PreviewConfirm.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { PreviewConfirm } from "../PreviewConfirm";
import type { BuilderPreview } from "../../../api/builder";

const _say = vi.fn();
const _deploy = vi.fn();
const _cancel = vi.fn();

vi.mock("../../../api/builder", () => ({
  builderApi: { say: (...args: any[]) => _say(...args) },
}));
vi.mock("../../../stores/builder", () => ({
  useBuilderStore: () => ({ deploy: _deploy, cancel: _cancel }),
}));

const _spec: BuilderPreview = {
  name: "treker-vody",
  description: "трекер",
  type: "skill",
  template: "tracker",
  config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
};

describe("PreviewConfirm", () => {
  beforeEach(() => {
    _say.mockReset().mockResolvedValue({ status: "ok", duration: 2 });
    _deploy.mockReset();
    _cancel.mockReset();
  });

  it("speaks the spec on mount", async () => {
    render(<PreviewConfirm spec={_spec} />);
    await waitFor(() => expect(_say).toHaveBeenCalled());
    const text = (_say.mock.calls[0][0] as string).toLowerCase();
    expect(text).toContain("treker-vody");
    expect(text).toContain("2 часа");
  });

  it("renders deploy + cancel buttons (a11y fallback)", () => {
    render(<PreviewConfirm spec={_spec} />);
    expect(screen.getByRole("button", { name: /запустить/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /отмена/i })).toBeInTheDocument();
  });

  it("clicking deploy fires store.deploy()", () => {
    render(<PreviewConfirm spec={_spec} />);
    fireEvent.click(screen.getByRole("button", { name: /запустить/i }));
    expect(_deploy).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run, verify failure**.

- [ ] **Step 3: Implement**

Replace the stub at `ui/src/components/VoiceBuilder/PreviewConfirm.tsx`:

```tsx
import { useEffect } from "react";
import { builderApi, type BuilderPreview } from "../../api/builder";
import { useBuilderStore } from "../../stores/builder";
import { SpecCard } from "./SpecCard";

const KEY_LABELS: Record<string, string> = {
  interval: "интервал",
  goal: "цель",
  notify_channel: "уведомление",
  time_window: "время",
  target: "url",
  trigger: "условие",
  categories: "категории",
};

const _buildReadbackText = (spec: BuilderPreview): string => {
  const parts = [`создаю ${spec.name}`];
  for (const [k, v] of Object.entries(spec.config ?? {})) {
    if (!v) continue;
    const label = KEY_LABELS[k] ?? k;
    parts.push(`${label} ${String(v)}`);
  }
  parts.push("подтверди");
  return parts.join(", ");
};

interface Props {
  spec: BuilderPreview;
}

export function PreviewConfirm({ spec }: Props) {
  const { deploy, cancel, setPreviewSubState } = useBuilderStore();

  useEffect(() => {
    let cancelled = false;
    // Awaits the full /tts/speak round-trip — Python's endpoint
    // returns only after audio playback finishes (`await
    // asyncio.to_thread(_play_audio, audio, sr)` at main.py:1418), so
    // by the time `say` resolves the speakers are silent and it's safe
    // to start mic capture without echoing the readback into STT.
    void builderApi
      .say(_buildReadbackText(spec), "ru")
      .finally(() => {
        if (!cancelled) setPreviewSubState("listening_for_command");
      });
    return () => {
      cancelled = true;
    };
  }, [spec, setPreviewSubState]);

  return (
    <div style={{ textAlign: "center" }}>
      <SpecCard spec={spec} highlighted={true} />
      <div style={{ marginTop: 24, display: "flex", gap: 12, justifyContent: "center" }}>
        <button
          type="button"
          onClick={() => void deploy()}
          style={{
            padding: "12px 24px",
            background: "var(--j-cyan)",
            color: "var(--j-bg)",
            border: "none",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          Запустить
        </button>
        <button
          type="button"
          onClick={() => void cancel()}
          style={{
            padding: "12px 24px",
            background: "transparent",
            color: "var(--j-text-dim)",
            border: "1px solid var(--j-border)",
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 16,
          }}
        >
          Отмена
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests, verify pass** — 3 passed.

- [ ] **Step 5: Commit**

```bash
git add ui/src/components/VoiceBuilder/PreviewConfirm.tsx ui/src/components/VoiceBuilder/__tests__/PreviewConfirm.test.tsx
git commit -m "feat(ui): PreviewConfirm — A6 readback + deploy/cancel buttons"
```

---

### Task 21: Audio re-start between turns + cross-turn sub-state wiring

**Files:**
- Modify: `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx`

**Why:** the `vad.onSilence` handler in Chunk 6 (Task 18) calls `audio.stop()` after every silence detection, which terminates capture. To listen for the next wizard answer (`asking/listening_for_answer`) or the preview voice command (`previewing/listening_for_command`), the screen needs to call `audio.start()` again after the TTS for that step finishes. This task wires those re-starts. Voice command parsing itself was already wired in Task 18's `vad.onSilence`; no separate parallel VAD needed.

- [ ] **Step 1: Add audio re-start useEffect to the screen**

Inside `VoiceBuilderScreen` (above `return`):

```tsx
// Re-start audio capture whenever we enter a listening sub-state.
// Single source of truth — no parallel VAD, no setTimeout fudge.
// PreviewConfirm and WizardPrompt both set their sub-state to "listening_*"
// only AFTER `say()` resolves (i.e. the speakers are silent), so mic-on
// won't echo TTS audio back into STT.
useEffect(() => {
  const shouldListen =
    (phase === "asking" && askingSubState === "listening_for_answer") ||
    (phase === "previewing" && previewSubState === "listening_for_command");

  if (!shouldListen) return;
  // Already recording? (e.g. orb tap → listening) — leave alone.
  if (audio.isRecording) return;

  let cancelled = false;
  void audio.start().catch(() => {
    // permission was revoked between turns
    if (!cancelled) setShowFallback(true);
  });

  return () => {
    cancelled = true;
  };
}, [phase, askingSubState, previewSubState]);
```

Note: `previewSubState` was added to the store in Chunk 4 (Task 10). Pull it from `useBuilderStore` alongside `askingSubState`.

- [ ] **Step 2: Pull `previewSubState` and `setPreviewSubState` from the store in the destructure**

In the destructure block at the top of the screen (Task 18 Step 2 code), add `previewSubState` and `setPreviewSubState` next to the existing `askingSubState` / `setAskingSubState` entries.

- [ ] **Step 3: Run typecheck + tests**

```bash
cd ui && npx tsc --noEmit && pnpm test
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx
git commit -m "feat(ui): cross-turn audio re-start when entering listening sub-states"
```

---

## Chunk 8: Polish — error UX + first-mount banner + e2e tests + manual rehearsal

**Why last:** Functional flow exists; this chunk hardens edge cases and runs the live test.

### Task 22: First-mount mic-permission intro banner (localStorage flag)

**Files:**
- Modify: `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx`

- [ ] **Step 1: Add the banner inside the screen**

Add inside the screen body, before the orb render:

```tsx
const FIRST_MOUNT_FLAG = "kali.voice_builder.intro_seen";

const [showIntro, setShowIntro] = useState(() => {
  try {
    return !window.localStorage.getItem(FIRST_MOUNT_FLAG);
  } catch {
    return true;
  }
});

const dismissIntro = () => {
  try {
    window.localStorage.setItem(FIRST_MOUNT_FLAG, "1");
  } catch {}
  setShowIntro(false);
};

// inside JSX, before the <VoiceOrb />:
{showIntro && (
  <div
    style={{
      maxWidth: 480,
      margin: "16px auto",
      padding: 16,
      background: "rgba(0,224,255,0.08)",
      border: "1px solid var(--j-border)",
      borderRadius: 8,
      color: "var(--j-text)",
    }}
  >
    <p style={{ marginBottom: 8 }}>
      Чтобы говорить с Jarvis, нужен доступ к микрофону. Нажми на микрофон и
      разреши доступ — это разовое действие.
    </p>
    <button
      onClick={dismissIntro}
      style={{
        background: "var(--j-cyan)",
        color: "var(--j-bg)",
        border: "none",
        padding: "6px 14px",
        borderRadius: 4,
        cursor: "pointer",
      }}
    >
      Понятно
    </button>
  </div>
)}
```

- [ ] **Step 2: Run tests + typecheck**

Run: `cd ui && pnpm test && npx tsc --noEmit`

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx
git commit -m "feat(ui): first-mount intro banner for mic permission"
```

---

### Task 23: Error-handling visible affordances

**Files:**
- Modify: `ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx`

- [ ] **Step 1: Surface common errors with contextual UX**

Inside the screen, replace the generic `{error && ...}` block with:

```tsx
{error && (
  <div
    style={{
      maxWidth: 480,
      margin: "12px auto",
      padding: 12,
      background: "rgba(248,113,113,0.12)",
      border: "1px solid #f87171",
      borderRadius: 6,
      color: "var(--j-text)",
    }}
  >
    <div style={{ marginBottom: 8 }}>{error}</div>
    <div style={{ display: "flex", gap: 8 }}>
      <button
        onClick={reset}
        style={{
          background: "transparent",
          color: "var(--j-text-dim)",
          border: "1px solid var(--j-border)",
          borderRadius: 4,
          padding: "4px 10px",
          cursor: "pointer",
        }}
      >
        Сбросить
      </button>
      <button
        onClick={() => setShowFallback(true)}
        style={{
          background: "transparent",
          color: "var(--j-text-dim)",
          border: "1px solid var(--j-border)",
          borderRadius: 4,
          padding: "4px 10px",
          cursor: "pointer",
        }}
      >
        Печатать вместо
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 2: Run tests + typecheck**

Run: `cd ui && pnpm test && npx tsc --noEmit`

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/VoiceBuilder/VoiceBuilderScreen.tsx
git commit -m "feat(ui): visible error recovery affordances on VoiceBuilderScreen"
```

---

### Task 24: End-to-end vitest covering golden + wizard fallback + cancel

**Files:**
- Create: `ui/src/components/VoiceBuilder/__tests__/VoiceBuilderScreen.test.tsx`

- [ ] **Step 1: Write the test**

```tsx
// ui/src/components/VoiceBuilder/__tests__/VoiceBuilderScreen.test.tsx
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceBuilderScreen } from "../VoiceBuilderScreen";
import { useBuilderStore } from "../../../stores/builder";

vi.mock("../../../api/builder", () => ({
  builderApi: {
    extract: vi.fn(),
    answer: vi.fn(),
    deploy: vi.fn(),
    cancel: vi.fn(),
    transcribe: vi.fn(),
    say: vi.fn().mockResolvedValue({ status: "ok", duration: 1 }),
    start: vi.fn(),
  },
}));

vi.mock("../useAudioCapture", () => ({
  useAudioCapture: () => ({
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue({ audio: new Uint8Array([0, 0]), sample_rate: 16000 }),
    isRecording: false,
  }),
}));

describe("VoiceBuilderScreen e2e", () => {
  beforeEach(() => {
    useBuilderStore.getState().reset();
    vi.clearAllMocks();
  });

  it("ESC anywhere triggers cancel via store", async () => {
    render(<VoiceBuilderScreen />);
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    // After cancel, store resets; phase back to idle.
    expect(useBuilderStore.getState().phase).toBe("idle");
  });

  it("text-fallback path: type + Enter → /builder/extract called", async () => {
    const { builderApi } = await import("../../../api/builder");
    (builderApi.extract as ReturnType<typeof vi.fn>).mockResolvedValue({
      complete: true,
      session_id: "sid",
      spec: {
        name: "treker", description: "", type: "skill", template: "tracker",
        config: { interval: "2 часа", goal: "2 литра", notify_channel: "чат" },
      },
    });

    render(<VoiceBuilderScreen />);
    fireEvent.click(screen.getByText(/печатать вместо/i));
    const input = await screen.findByPlaceholderText(/трекер/i);
    fireEvent.change(input, { target: { value: "трекер 2л 2ч в чат" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(builderApi.extract).toHaveBeenCalled());
  });
});
```

- [ ] **Step 2: Run, verify pass** — `cd ui && pnpm test -- VoiceBuilderScreen` → green.

- [ ] **Step 3: Commit**

```bash
git add ui/src/components/VoiceBuilder/__tests__/VoiceBuilderScreen.test.tsx
git commit -m "test(ui): VoiceBuilderScreen e2e (cancel + text-fallback)"
```

---

### Task 25: Manual rehearsal + handoff

**Files:**
- Create: `.claude/handoffs/2026-MM-DD-voice-builder-pilot.md` (use today's date at execution time)

- [ ] **Step 1: Build the app + start backend**

Run, in two shells:
```bash
.venv/Scripts/python.exe -m kernel.main
```
```bash
pnpm --dir ui build && cargo run --manifest-path src-tauri/Cargo.toml
```

(The codebase uses pnpm — `ui/pnpm-lock.yaml` exists, no `package-lock.json`. Don't substitute `npm`.)

- [ ] **Step 2: Manual rehearsal — 5 voice runs back-to-back**

Reset the first-mount banner before starting (`localStorage.removeItem("kali.voice_builder.intro_seen")` in the Tauri devtools console) so each rehearsal exercises the cold start.

Voice-say each prompt and record what the extractor classified. Target ≥4/5 success — "success" = correct template + at least the dominant config field correctly populated + agent deploys without backend error.

| # | Prompt | Expected template | Expected config keys filled | Result |
|---|--------|-------------------|----------------------------|--------|
| 1 | трекер воды два литра каждые два часа в чат | tracker | interval=2 часа, goal=2 литра, notify_channel=чат | |
| 2 | напоминай делать растяжку каждый час | reminder | interval=каждый час | |
| 3 | проверяй курс биткоина каждые пять минут и уведомляй в телеграм если упал на пять процентов | notifier | trigger=*5%* / *упал*, notify_channel=телеграм | |
| 4 | веди дневник настроения раз в день голосом | logger | categories=настроение | |
| 5 | следи за сайтом example.com каждые десять минут и уведомляй если недоступен | monitor | target=example.com, interval=10 минут | |

If a prompt mis-classifies the template, that's a fail (prompt + extracted-template-was-X in a row).

- [ ] **Step 3: Fix any issues found during rehearsal**

Map symptoms to likely fixes (cross-reference spec lines 481-491 for the documented error envelope):
- STT mishears (~40% of word loss): tune `useRmsVad` threshold (calibration delta in `useAudioCapture`); too-eager 1.5s silence cut-off — bump to 2000ms.
- TTS readback feels slow: confirm Task 9's lifespan prewarm fired in the kernel log on startup ("TTS prewarm: ready").
- Wrong template: extractor LLM prompt may need a worked example for that pattern; add to `LLM_SYSTEM_PROMPT` as an example block.
- Deploy fails: check `kernel/builder/deployer.py` — most likely a name collision (existing skill with same slug) — re-test with a different agent name in the prompt.

If symptom isn't covered by the spec's error table, surface to user before guessing — spec line 537 ("zero broken states") promises a documented recovery for everything.

- [ ] **Step 4: Update memory + write handoff**

Update `memory/MEMORY.md` head pointer + add a row to `memory/project_roadmap.md` revision history (v2.13 — voice-builder-pilot SHIPPED). Write a fresh handoff at `.claude/handoffs/<today>-voice-builder-pilot.md` summarising chunks shipped, rehearsal result, and what's left for Tier 2 #10.

- [ ] **Step 5: Commit**

```bash
git add memory/ .claude/handoffs/
git commit -m "docs(handoff): voice-builder-pilot v2 SHIPPED + rehearsal results"
```

---

## Final review

After all 25 tasks:

```bash
.venv/Scripts/python.exe -m pytest tests/ -x
cd ui && pnpm test && npx tsc --noEmit
cargo test --manifest-path src-tauri/Cargo.toml
cargo check --manifest-path src-tauri/Cargo.toml --features ml-tests --tests
cargo check --manifest-path src-tauri/Cargo.toml --features audio-tests --tests
```

All green → pilot ready for friend distribution. `mode === "builder"` accessible via Sidebar + (after Agent Store v2 lands) hero CTA.

---

## Out-of-scope / Future work (tracked separately)

- Hero CTA wire-up in Agent Store v2 (Tier 2 #10 brainstorm).
- Global wake-word "hey jarvis, создай агента" → mode switch.
- localStorage session persistence across reload.
- A1 per-step voice confirms / A3 STT confidence-gate / A5 voice barge-in.
- Existing agent remix.
- Custom Python agent generation (Tier 3 #18).
