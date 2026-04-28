# Rust Migration Phase 4 — Skills Catalog + Installer

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move skills catalog browsing, local registry, install/uninstall, validation, and the legacy `.kali-agent` package format from Python (`kernel/skills/*.py`) to Rust (`src-tauri/src/backend/skills/*.rs` + `backend/skills/package.rs`). After this phase, the UI's skills/catalog flows hit Rust on `:3006`; Python keeps only what *can't* be ported (skill execution, since skills are Python code).

**Architecture delta after this phase:**

```
Before Phase 4 (today):
  Python kernel.entry on :3005 owns:
    kernel/skills/{loader,registry,catalog,installer,validator,publisher,converter}.py
  UI hits Python for /skills, /skills/installed, /skills/catalog, /skills/install, etc.
  Rust on :3006 has no skills knowledge.

After Phase 4:
  Rust on :3006 owns:
    backend/skills/{mod,loader,registry,catalog,installer,validator,package}.rs
    plus native handlers for the 12+ /skills and /catalog endpoints listed below.
  Python keeps:
    - POST /skills/{name}/{action}  (skill execution — skills are Python code)
    - POST /skills/publish          (GitHub PR creation; complex auth, deferred)
    - /agents/*                     (agent runtime is Python; Phase 5 or 8 deals)
  UI dispatcher (RUST_ENDPOINTS) gains all ported routes incrementally.
```

**Tech stack additions:**
- `walkdir = "2"` — directory traversal for SKILL.md discovery (no transitive bloat).
- `zip = "2"` — read/write `.kali-agent` archives (Chunk 5). Defaults are fine; no native deps.
- `reqwest`, `serde_yaml`, `serde_json` — already present from Phase 1+3.

**Prerequisites:**
- Phase 3 SHIPPED. Bridge primitive proven. Voice handlers pattern (Extension dispatch) reusable for skills handlers.
- Spec read: `docs/superpowers/specs/2026-04-24-rust-backend-migration.md` §5 (module map), §6 (HTTP contract preservation).
- Memory: `project_rust_migration.md` operational patterns — Extension layer pattern, contract-test pattern, proxy fallback dispatch.

**Unblocks:**
- Tier 2 #10 (Agent Store v2) — needs Rust skills catalog API for the polished store surface.
- Tier 2 #11 (Rust Phase 5 — Builder) — Builder produces skills; once Rust owns the registry, Builder writes there directly.
- Phase 8 retire of `kernel/skills/{loader,registry,catalog,installer,validator}.py`.

**Scope carve-outs (explicitly deferred):**
- **`POST /skills/{name}/{action}` (execution)** — proxies to Python. Skills are Python code; the Python `SkillExecutor` runtime owns this. Same precedent as STT/wake-word path B.
- **`POST /skills/publish`** — creates GitHub PRs. Auth + branching logic is non-trivial. Phase 6+ if Vasily decides it's needed for public launch; otherwise stays in Python.
- **`kernel/skills/converter.py`** — converts old format to SKILL.md. Legacy migration tool, low-traffic. Deprecate in place; not ported.
- **`/agents/*` (load/unload/execute/status)** — Python agent runtime owns these. Phase 5 (Builder) or Phase 8 cleanup.
- **Hot-reload of installed skills** — restart required to pick up new skills. Phase 6+ feature if it becomes a friction point.

---

## Module Map

| Python source | Rust target | Notes |
|---|---|---|
| `kernel/skills/loader.py` | `backend/skills/loader.rs` | walkdir + serde_yaml frontmatter |
| `kernel/skills/registry.py` | `backend/skills/registry.rs` | `Arc<RwLock<HashMap>>` for hot lookups |
| `kernel/skills/catalog.py` | `backend/skills/catalog.rs` | reqwest GitHub API + file cache |
| `kernel/skills/installer.py` (SKILL.md path) | `backend/skills/installer.rs` | install_from_catalog + uninstall |
| `kernel/skills/installer.py` (.kali-agent path) | `backend/skills/package.rs` | zip + json metadata |
| `kernel/skills/validator.py` | `backend/skills/validator.rs` | spec rules over parsed manifest |

Endpoints ported (organised by chunk):

| Chunk | Endpoint | Method |
|-------|----------|--------|
| 1 | `/skills` | GET |
| 1 | `/skills/installed` | GET |
| 2 | `/skills/catalog/sources` | GET |
| 2 | `/skills/catalog` | GET |
| 2 | `/skills/catalog/refresh` | POST |
| 3 | `/skills/install` | POST |
| 3 | `/skills/uninstall` | POST |
| 4 | `/skills/validate` | POST |
| 5 | `/catalog/search` | GET |
| 5 | `/catalog/trending` | GET |
| 5 | `/catalog/pack/{name}` | POST |
| 5 | `/catalog/install` | POST |
| 5 | `/catalog/info` | GET |

Endpoints NOT ported (proxy to Python via `proxy_*_json`):

| Endpoint | Method | Why proxy |
|----------|--------|-----------|
| `/skills/{name}/{action}` | POST | Skills are Python code; SkillExecutor stays. |
| `/skills/publish` | POST | Defer. |
| `/agents/*` (5 routes) | various | Phase 5+. |

---

## Chunk 1: Local Skills Registry — `GET /skills`, `GET /skills/installed`

**What:** Discover SKILL.md files under `agents/` (and any user-skill paths from config), parse the YAML frontmatter into a `SkillManifest`, expose via two read-only endpoints. No write paths, no remote fetch — pure local filesystem read.

**Why first:** Smallest surface. Read-only is forgiving — wrong output just means UI shows fewer skills, never breaks Python's installer underneath. Lets us prove the dispatch pattern (Extension layer, conditional native/proxy) for skills before any write semantics.

### Files
- Create: `src-tauri/src/backend/skills/mod.rs` — module root, re-exports.
- Create: `src-tauri/src/backend/skills/loader.rs` — `discover_skills(root: &Path) -> Vec<SkillManifest>`, frontmatter parser.
- Create: `src-tauri/src/backend/skills/registry.rs` — `SkillsRegistry { skills: Arc<RwLock<HashMap<String, SkillManifest>>> }` with `reload()`, `list_all()`, `get(name)`.
- Modify: `src-tauri/src/backend/mod.rs` — declare `pub mod skills;`, build registry in `serve()`.
- Modify: `src-tauri/src/backend/http.rs` — add `/skills` + `/skills/installed` handlers + Extension dispatch (similar to voice routes).
- Modify: `src-tauri/Cargo.toml` — `walkdir = "2"`.
- Modify: `ui/src/api/endpoints.ts` — add the 2 routes to `RUST_ENDPOINTS`.
- Create: `src-tauri/tests/skills_registry.rs` — integration test with a temp dir of fake SKILL.md files.

### Tasks (TDD-disciplined)
- [ ] **RED:** integration test — temp dir with 2 sample SKILL.md files → registry returns 2 manifests with expected names. Run `cargo test --test skills_registry` → fails (registry doesn't exist).
- [ ] **GREEN loader:** implement `discover_skills` (walkdir + frontmatter parse).
- [ ] **GREEN registry:** implement `SkillsRegistry::new(root)` + `reload()` + `list_all()`.
- [ ] **Unit tests:** parse frontmatter happy path + missing required field → error.
- [ ] **GREEN routes:** native `/skills` and `/skills/installed` handlers via `Extension<Arc<SkillsRegistry>>`. Proxy fallback when registry is `None`.
- [ ] **Wire in serve():** construct registry, attach as Extension. Failure to discover any skills is NOT fatal (just empty list).
- [ ] **UI dispatcher:** add `GET /skills` + `GET /skills/installed` to `RUST_ENDPOINTS`.
- [ ] **Verify:** cargo test default green; pnpm test + tsc unchanged.
- [ ] **Commit:** `feat(skills): local SKILL.md registry + read-only routes (Phase 4 Chunk 1)`

**Estimate:** ~1 day.

---

## Chunk 2: Remote Catalog Client — `GET /skills/catalog/sources`, `GET /skills/catalog`, `POST /skills/catalog/refresh`

**What:** Port `kernel/skills/catalog.py`. Fetch skill manifests from configured GitHub sources (the `sources` list in `kernel/skills/catalog_sources.yaml`), cache results to disk, expose listing endpoints with optional source/query filtering.

### Files
- Create: `src-tauri/src/backend/skills/catalog.rs` — `CatalogClient`, `CatalogEntry`, `CatalogSource` structs + GitHub fetch.
- Create: `src-tauri/src/backend/skills/cache.rs` — file-based JSON cache (`%APPDATA%/KALI/cache/skills/` on Windows, XDG cache dir on Linux/macOS), 24h default TTL.
- Modify: `src-tauri/src/backend/http.rs` — add catalog routes + Extension dispatch.
- Modify: `src-tauri/src/backend/mod.rs` — build `CatalogClient` in `serve()`, share via Extension.
- Modify: `ui/src/api/endpoints.ts` — add 3 routes to `RUST_ENDPOINTS`.
- Create: `src-tauri/tests/skills_catalog.rs` — mock GitHub via local axum server, verify fetch + parse + cache round-trip.

### Tasks
- [ ] **RED:** integration test — mock GitHub returning a 2-skill manifest → `CatalogClient::fetch_source` returns 2 entries; second call within TTL hits cache (no second HTTP call).
- [ ] **GREEN client:** implement HTTP fetch (reqwest) + JSON parse.
- [ ] **GREEN cache:** disk-backed cache with TTL. Store under `dirs::cache_dir().join("kali/skills")`.
- [ ] **GREEN routes:** `/skills/catalog/sources` returns the configured sources list; `/skills/catalog` lists entries with optional `?source=` and `?q=` filters; `/skills/catalog/refresh` (POST, `{"force": true}`) re-fetches all sources and returns total count.
- [ ] **Source config loading:** read `config/catalog_sources.yaml` (matching Python's location) on startup. Fall back to a hardcoded default of the `anthropic-skills` source if missing.
- [ ] **Verify:** cargo test default green; UI dispatcher updated; rate-limit risk addressed via cache TTL.
- [ ] **Commit:** `feat(skills): remote catalog client over GitHub (Phase 4 Chunk 2)`

**Estimate:** ~1.5 days.

**Risks:**
- **GitHub rate limits** during refresh — cache 24h by default. Add `If-Modified-Since` header support if rate-limit shows up in dev.
- **Catalog source format drift** — Python source uses YAML frontmatter inside individual skill repos. Match the exact parser logic; pin a contract test.

---

## Chunk 3: Skill Installer — `POST /skills/install`, `POST /skills/uninstall`

**What:** Port the SKILL.md-format install path from `kernel/skills/installer.py`. Download the skill folder from GitHub (per a `CatalogEntry`), validate, copy into `agents/<name>/`, and reload the registry. Uninstall is the reverse — remove the directory, reload registry.

### Files
- Create: `src-tauri/src/backend/skills/installer.rs` — `install_from_catalog(entry, opts) -> InstallResult`, `uninstall(name) -> bool`.
- Modify: `src-tauri/src/backend/http.rs` — add `/skills/install` + `/skills/uninstall` routes.
- Modify: `ui/src/api/endpoints.ts` — add the 2 routes.
- Create: `src-tauri/tests/skills_install.rs` — full install round-trip via local-fixture catalog source.

### Tasks
- [ ] **RED:** integration test — install a known-good fixture skill, verify `agents/<name>/SKILL.md` exists, registry reload picks it up. `cargo test --test skills_install` fails (route doesn't exist).
- [ ] **GREEN install:** download skill folder (GitHub `tarball` or `tree` API), extract to staging dir, validate (Chunk 4's validator if landed; else basic frontmatter sanity), atomic rename to `agents/<name>/`. Cleanup staging on error.
- [ ] **GREEN uninstall:** verify the path is under `agents/`, refuse builtin skills, recursive remove.
- [ ] **`overwrite` flag:** body `{"overwrite": true}` allows replacing an existing skill directory.
- [ ] **Registry hook:** after install/uninstall, call `registry.reload()` so `/skills/installed` reflects immediately.
- [ ] **Path-traversal hardening:** every extracted path must canonicalise inside the staging dir. Reject `..` in archive entries.
- [ ] **Verify + commit:** `feat(skills): installer (install_from_catalog + uninstall) (Phase 4 Chunk 3)`

**Estimate:** ~1 day.

**Risks:**
- **Partial install** leaving broken state — staging dir + atomic rename. If anything fails mid-extraction, the staging dir is removed; the live `agents/<name>/` is untouched.
- **Builtin-skill protection** — refuse to uninstall anything inside `agents/builtin/` (or whatever Python uses). Read the Python guard logic and match.

---

## Chunk 4: Validator — `POST /skills/validate`

**What:** Port `kernel/skills/validator.py`. Given an installed skill name, run spec checks (required frontmatter fields, allowed `dependencies` keys, `model` enum bounds, etc.) and return warnings + errors.

### Files
- Create: `src-tauri/src/backend/skills/validator.rs` — `validate_skill(manifest: &SkillManifest) -> ValidationReport { errors, warnings }`.
- Modify: `src-tauri/src/backend/http.rs` — add `/skills/validate` route.
- Modify: `ui/src/api/endpoints.ts` — add the route.
- Add unit tests inline + 1 integration test against a fixture with known violations.

### Tasks
- [ ] Read `kernel/skills/validator.py` end-to-end. Document each rule. Port one-for-one — no new rules, no skipped rules.
- [ ] **RED:** unit tests for each rule (required name, required description, dependencies allowlist, model enum, etc.).
- [ ] **GREEN:** implement `validate_skill` matching Python rules.
- [ ] **Route:** body `{"name": "..."}` → look up via registry → run validator → return JSON `{errors: [], warnings: []}`.
- [ ] **Verify + commit:** `feat(skills): SKILL.md validator (Phase 4 Chunk 4)`

**Estimate:** ~0.5 day.

---

## Chunk 5: Legacy `.kali-agent` Package Format — `/catalog/*` routes

**What:** Port the older package-based catalog flow (predates SKILL.md) — `.kali-agent` files (zip with `manifest.yaml`), pack/unpack/install/info, plus search-and-trending against the local agents directory and the cloud catalog client. Five routes, all currently in Python.

### Files
- Create: `src-tauri/src/backend/skills/package.rs` — `pack_agent`, `install_package`, `get_package_info`. Uses `zip` crate for archive I/O.
- Modify: `src-tauri/src/backend/http.rs` — add `/catalog/search`, `/catalog/trending`, `/catalog/pack/{name}`, `/catalog/install`, `/catalog/info` handlers.
- Modify: `ui/src/api/endpoints.ts` — add the 5 routes.
- Modify: `src-tauri/Cargo.toml` — `zip = "2"`.
- Create: `src-tauri/tests/skills_package.rs` — pack-then-unpack round trip.

### Tasks
- [ ] **RED:** test packs an agent dir into `.kali-agent`, then installs it back into a fresh dir, verifies file equality.
- [ ] **GREEN pack:** zip the agent directory + write a `manifest.yaml` summary at the root. Output to `exports/<name>.kali-agent`.
- [ ] **GREEN install_package:** validate the archive header, extract to staging, atomic rename. Same path-traversal hardening as Chunk 3.
- [ ] **GREEN get_package_info:** read manifest.yaml from inside an unopened `.kali-agent` (zip directory listing without full extraction).
- [ ] **Search + trending:** `/catalog/search` returns local agents matching `?q=`; `/catalog/trending` returns local + cloud (when CatalogClient has data).
- [ ] **Verify + commit:** `feat(skills): .kali-agent package format support (Phase 4 Chunk 5)`

**Estimate:** ~1.5 days.

**Risks:**
- **Zip-bomb / path traversal** — cap the total extracted size (e.g. 100 MB) and reject any archive entry whose canonical path escapes the staging dir.
- **Format drift** between Python's zip and Rust's — pin a fixture `.kali-agent` file under `tests/fixtures/` from Python's pack, install it via Rust to ensure parity.

---

## Success Criteria (whole phase)
- All 5 chunks shipped, each as one atomic commit.
- `cargo test` default green at every commit. New tests added per chunk land in the default suite (no gating beyond the existing `ml-tests` / `audio-tests` features which Phase 4 doesn't touch).
- `cargo check --features ml-tests --tests` and `--features audio-tests --tests` both stay clean — Phase 4 doesn't change voice code.
- UI dispatcher (`RUST_ENDPOINTS`) gains 13 entries across the 5 chunks. UI tests + tsc unchanged.
- Python `/skills/*` and `/catalog/*` endpoints remain functional as fallback (any non-ported route, any client that hits Python directly, still works).
- Memory `project_rust_migration.md` Phase 4 row marked SHIPPED with the closing commit hash.

## Out of Scope (deferred — see also "Scope carve-outs" above)
- Skill execution route (`/skills/{name}/{action}`). Stays Python.
- Publish route. Stays Python.
- Agent endpoints. Phase 5 / Phase 8.
- Format conversion (`converter.py`). Deprecate.

## Risks Revisited
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| YAML frontmatter parse drift between Python and Rust | Med | High | Parity test in Chunk 1: load same SKILL.md in both, assert identical struct. |
| GitHub rate limits during catalog refresh | Med | Med | 24h cache TTL; honor `If-Modified-Since` in Chunk 2. |
| Partial-install broken state | Med | High | Staging dir + atomic rename, both for SKILL.md and `.kali-agent` paths. |
| `.kali-agent` zip bombs / path traversal | Low | High | Validate paths + cap extracted size. Standard archive-handling hygiene. |
| Skill registry hot-reload missing edge cases | Low | Med | Restart-required is documented; Phase 6+ adds inotify if needed. |
| Existing UI breaks on subtle JSON shape diffs | Med | High | Golden-file contract tests per Phase 1 pattern; UI types compile-check. |

## Estimate
~5.5 days = ~1 week solo. Matches spec §12. Chunk 5 (legacy `.kali-agent`) is the highest-variance — budget a half-day spike if zip integration on Windows surprises.

---

**Plan-execution discipline reminders:**
- Each chunk closes with green tests + a single atomic commit. Don't batch chunks.
- Read `memory/project_rust_migration.md` at the start of each chunk for cross-phase invariants (Extension dispatch pattern, contract-test pattern, env var configurability).
- For any > 30 min sub-step inside a chunk, write a short sub-plan first (the `feedback_session_patterns.md` rule).
- Skill execution routes stay proxied — same path B precedent set by STT and wake-word.
