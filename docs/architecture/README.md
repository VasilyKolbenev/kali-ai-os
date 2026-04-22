# KALI Architecture Documentation

This folder contains C4-model architecture diagrams for KALI — Personal AI OS.

**Convention:** [C4 Model](https://c4model.com) by Simon Brown. Diagrams written in **PlantUML** (C4-PlantUML stdlib).

## Diagram Index

| Level | `.md` (narrative + code) | `.puml` (standalone) | Audience |
|-------|--------------------------|----------------------|----------|
| 1 | [c4-context.md](c4-context.md) | [c4-context.puml](c4-context.puml) | Everyone |
| 2 | [c4-containers.md](c4-containers.md) | [c4-containers.puml](c4-containers.puml) | Technical |
| 3 | [c4-components-backend.md](c4-components-backend.md) | [c4-components-backend.puml](c4-components-backend.puml) | Developers |
| 3 | [c4-components-voice-builder.md](c4-components-voice-builder.md) | [c4-components-voice-builder.puml](c4-components-voice-builder.puml) | Developers |
| — | *(embedded in voice-builder md)* | [voice-builder-state-machine.puml](voice-builder-state-machine.puml) | Session lifecycle |
| — | *(embedded in voice-builder md)* | [voice-builder-dynamic.puml](voice-builder-dynamic.puml) | Happy-path sequence |

## How to Render

PlantUML doesn't render natively on GitHub. Pick one:

**PlantUML Web (easiest):**
1. Open https://www.plantuml.com/plantuml
2. Paste the entire content of any `.puml` file (or the `plantuml` code block inside `.md`)
3. See rendered diagram instantly. Export PNG/SVG/PDF.

**VSCode extension (for editing + live preview):**
1. Install [PlantUML extension](https://marketplace.visualstudio.com/items?itemName=jebbs.plantuml)
2. Open any `.puml` file → `Alt+D` for preview
3. Requires local Java or uses the public server

**Local CLI (for CI/build pipelines):**
```bash
# Download plantuml.jar from plantuml.com/download
java -jar plantuml.jar docs/architecture/*.puml -tpng -o rendered/
```

**Note on `!include` directives:** Our diagrams pull C4-PlantUML stdlib from GitHub raw URLs. PlantUML Web public server permits this by default. Private/self-hosted servers may need `allow_include` setting enabled.

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
