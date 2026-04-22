# KALI Architecture Documentation

This folder contains C4-model architecture diagrams for KALI — Personal AI OS.

**Documentation convention:** [C4 Model](https://c4model.com) by Simon Brown. Diagrams use Mermaid syntax (C4 extension) — render natively on GitHub and most Markdown viewers.

## Diagram Index

| Level | Document | Audience | Purpose |
|-------|----------|----------|---------|
| 1 | [c4-context.md](c4-context.md) | Everyone | KALI's place in the world — who uses it, what it talks to |
| 2 | [c4-containers.md](c4-containers.md) | Technical | Main deployable units — Tauri shell, FastAPI backend, local models, external APIs |
| 3 | [c4-components-backend.md](c4-components-backend.md) | Developers | Python backend internals — kernel modules, voice pipeline, builder, sandbox |
| 3 | [c4-components-voice-builder.md](c4-components-voice-builder.md) | Developers | Voice builder flow — how "скажи идею → агент за 60s" works (pilot design) |

## Reading Order

**New to KALI?** Start with [c4-context.md](c4-context.md), then [c4-containers.md](c4-containers.md).

**Backend developer?** Read [c4-components-backend.md](c4-components-backend.md) after containers.

**Working on builder pilot?** Jump straight to [c4-components-voice-builder.md](c4-components-voice-builder.md) — it assumes container-level familiarity.

## When to Update

Update these diagrams when:
- A new **external system** is integrated (new API, new source) → update Context
- A new **deployable unit** added (new service, new local model) → update Containers
- A **major module** added/removed in backend → update Components
- A **new flow** becomes critical enough to model (like voice-builder pilot) → add a new Components or Dynamic diagram

Do NOT update for: file-level refactors, renames, small features that fit existing boxes.

## Related

- [VISION.md](../../VISION.md) — product thesis, roadmap, business model
- [CLAUDE.md](../../CLAUDE.md) — coding conventions and quick project intro
- [docs/superpowers/plans/](../superpowers/plans/) — active implementation plans
