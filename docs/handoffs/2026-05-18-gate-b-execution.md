# Gate B — Voice-builder-pilot Task 25 rehearsal

> Created 2026-05-18 during max-confidence debug session.
> **Blocked by:** wake-word working (smoke test #1) + builder mode reachable.
> Estimated execution time: 30-45 minutes.

## What Gate B is

The last 25th task from voice-builder-pilot v2 plan (`docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md` — frontend completed Apr 29 at 24/25). The 25th task = **manual rehearsal** of voice-driven agent creation. ≥4 of 5 prompts must succeed end-to-end (correct template + correct dominant config field + clean deploy).

Closes voice-builder-pilot v2 entirely once 4/5 hit.

## Prerequisites

1. **Smoke test #1 passing** — wake-word triggers, STT transcribes, F5-TTS responds.
2. **Builder mode reachable** — KALI sidebar has builder icon; clicking it opens "Создать агента" screen with mic button.
3. **OpenAI API key valid** (the builder uses LLM for intent classification + skill generation).
4. **Dev backend running** with `KALI_WAKE_THRESHOLD=0.15` (so wake-word triggers reliably) and the latest `.env` synced (DFMA OpenAI key from APPDATA).

## The 5 test prompts (from Apr 29 handoff)

| # | Voice prompt | Expected template | Expected dominant config field | Expected deploy |
|---|---|---|---|---|
| 1 | *"Создай агента: трекер воды два литра каждые два часа в чат"* | `tracker` | `amount: 2 liters`, `interval: 2 hours`, `channel: chat` | New agent "water-tracker-XXXX" deployed |
| 2 | *"Создай напоминалку: напоминай делать растяжку каждый час"* | `reminder` | `interval: 1 hour`, `message: "растяжка"` | Reminder agent deployed |
| 3 | *"Создай агента: проверяй курс биткоина каждые пять минут и уведомляй в телеграм если упал на пять процентов"* | `notifier` | `threshold: -5%`, `interval: 5 min`, `channel: telegram` | Notifier agent deployed |
| 4 | *"Создай агента: веди дневник настроения раз в день голосом"* | `logger` | `frequency: daily`, `input_mode: voice` | Logger agent deployed |
| 5 | *"Создай агента: следи за сайтом example.com каждые десять минут и уведомляй если недоступен"* | `monitor` | `url: example.com`, `interval: 10 min`, `alert_on: down` | Monitor agent deployed |

## Execution loop (per prompt)

For each of the 5 prompts:

1. In KALI UI, click sidebar Builder icon → "Создать агента" screen.
2. Click the **microphone button** (or it may auto-start when entering builder mode).
3. Wait for orb pulse → state → `listening`.
4. Say the prompt EXACTLY (Russian, calmly).
5. After silence, the wizard:
   - Echoes transcribed text
   - Classifies intent (template + confidence)
   - Asks ≤3 clarifying questions if needed
   - Generates a preview spec
   - Shows "Готово, запускать?" → say **"Да"** to deploy
6. Verify in Agents tab — new agent appears with the right name and status `running`.

**Scoring:** prompt counts as **success** if all 3 are true:
- Template name matches expected (column 3)
- Config has the expected dominant field present (column 4)
- Deploy reports success and agent shows up in Agents tab

**Failure mode tolerance:** 1/5 may fail without blocking gate. ≤2/5 fail = gate fails, debug + retry.

## What "success" looks like at the end

```
1. tracker     OK
2. reminder    OK
3. notifier    OK
4. logger      OK
5. monitor     ?

→ 4/5 = GATE PASSED
```

Or:

```
1. tracker     OK
2. reminder    template misclassified (notifier instead) ← FAIL #1
3. notifier    OK
4. logger      OK
5. monitor     deploy hung ← FAIL #2

→ 3/5 = GATE FAILED, debug
```

## Recording the result

After the rehearsal, write to `memory/feedback_voice_builder_pilot_v2_rehearsal.md`:

```markdown
# Voice-builder-pilot v2 Task 25 rehearsal — 2026-05-XX

| # | Prompt (one-liner) | Result | Notes |
|---|---|---|---|
| 1 | трекер воды | ✓ | template=tracker, deployed cleanly |
| 2 | напоминалка растяжки | ✓ | template=reminder, asked 1 clarifying ("какое время начала?") |
| 3 | биткоин 5% телеграм | ✗ | template=notifier OK but config missed `channel: telegram`; user had to retype manually |
| 4 | дневник настроения | ✓ | template=logger |
| 5 | мониторинг example.com | ✓ | template=monitor |

**Score: 4/5 — GATE PASSED.**

Plan-defects caught: 1
- F3 prompt: telegram-channel extraction failed for "уведомляй в телеграм" — issue tracked as chip.
```

Then update `memory/project_roadmap.md` v2.16:
```
- voice-builder-pilot v2 — 25/25 SHIPPED (Apr 29 + 2026-05-XX rehearsal)
```

## What to do if gate fails

1. **Don't retry the same way.** Each failed prompt is data — record exactly what went wrong.
2. **Categorize failures:**
   - **Template misclassification** → intent_classifier issue (regex patterns or LLM prompt)
   - **Config extraction missed a field** → skill_generator template prompt
   - **Deploy hung** → safety_gate or deployer infrastructure
   - **Wake-word never triggered** → not a builder issue, separate fix
3. **For 1-2 misses:** spawn chip with specific defect, retry once after fix.
4. **For ≥3 misses:** voice-builder-pilot v2 has deeper issues → write a follow-up spec, don't force-close gate.

## Reference

- Source plan: `docs/superpowers/plans/2026-04-28-voice-builder-pilot-v2.md` (Apr 28-29, 25 tasks)
- Frontend completion handoff: `.claude/handoffs/2026-04-29-voice-builder-pilot-v2-frontend-complete.md`
- Plan-defects already caught (8 from Apr 29): in the same handoff
