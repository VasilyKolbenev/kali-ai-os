# Agent Python Generation (LLM) — Plan Stub

> Status: STUB. Написан 2026-04-22. Full detail пишется после того как voice-builder-pilot показал стабильность skill creation minimum 2 недели с real users.

**Goal:** Включить второй путь в BuilderFlow — генерация кастомного Python-агента через LLM (используя существующий `kernel/builder/agent_generator.py` + `safety_gate.py`) для use cases которые не вписываются в skill templates.

**Depends on:**
- voice-builder-pilot проверен на 5+ real users 2+ недели
- 0 critical bugs в skill creation pipeline
- Intent classifier имеет accuracy ≥90% в production (нужны metrics)

## Why НЕ сейчас (важно зафиксировать)

Skills = deterministic, fast, safe. Agents = non-deterministic, slow (LLM call), potentially unsafe. Включать вторую ветку пока первая не проверена — умножить failure modes на 2.

Даже если код готов (agent_generator.py уже написан), включать его в prod без baseline intent_classifier stats — russian roulette для user trust.

## Trigger conditions для включения

- [ ] voice-builder-pilot работает у ≥5 real users
- [ ] NEW user → first deployed skill за ≤60 сек (aggregate median) держится 2 недели
- [ ] Skill deploy success rate ≥95% (rollbacks отслеживаются)
- [ ] Intent classifier accuracy ≥90% (measured on real prod traffic)

Без этих условий — не включаем.

## Scope when enabled

**In:**
1. BuilderFlow.start() перестаёт raise если intent.type == "agent" (снять guard)
2. Extended wizard questions для agents (current agent_questions() слабоват)
3. Preview для agent shows generated Python code (collapsed, "Показать код" toggle)
4. Runtime cost metering — LLM call tracking в audit log (cost by user, by agent)
5. Soft rate limit per user (anti-abuse)
6. Code explanation на естественном языке (для non-tech user понимания что агент делает)

**Out:**
- Multi-file agents (single file only, enforced by agent_generator)
- Agent inter-communication (complex scope)
- Custom dependencies beyond stdlib + requests (safety gate blocks others)

## Risks

- **LLM hallucinates non-existent APIs** — safety_gate catches some but not all. Need runtime error recovery.
- **Generated code slow** — LLM не оптимизирует performance. Need timeout on agent execution.
- **User can't debug generated Python** — non-tech persona не прочитает stack trace. Need "я не смог, давай переделаем" voice flow.
- **Cost explosion** — если популярный use case triggers agent path для каждого user, LLM bill растёт quadratic. Need dedup cache.

## Estimate

~3 дня wiring + ~2 дня quality testing с real LLM calls (не mocked).

## Rollout strategy

1. Behind feature flag (AGENT_GENERATION_ENABLED env var) — off by default
2. Opt-in для beta users (UI toggle "Разрешить генерацию агентов через AI")
3. Monitor metrics 1 неделю на 10% traffic
4. Full rollout если metrics зелёные
