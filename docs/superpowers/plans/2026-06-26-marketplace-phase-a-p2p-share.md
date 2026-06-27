# Marketplace Phase A — P2P share→friend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a voice-built agent (manifest.yaml + skill.yaml, **no** SKILL.md, under `agents_dir`) survive the full P2P round-trip — exportable as the shipped base64url `.tar.gz` bundle, installable on a friend's device, and **LLM-callable after import** — with zero new infrastructure.

**Architecture:** Three surgical changes on the **SEND** side + one irreducible fix on the **RECEIVE/registry** side; the install route, transport envelope, and `kali://` deep link are **untouched** (commit 2d already wired live-registration; the transport is already byte-consistent). (1) `PluginRegistry` tracks every agent's real source dir in a `self._dirs` map and `_is_callable` consults it (fixes "imported skill withheld from LLM palette"). (2) `package_skill` synthesizes a minimal spec-valid SKILL.md when none exists and carries `manifest.yaml`+`skill.yaml` into the tarball (so the existing SKILL.md-based loader/validator accept it and the imported skill stays runnable). (3) the export route falls back to the plugin registry when the SKILL.md-indexed `SkillsRegistry` misses.

**Tech Stack:** Python 3.12 / FastAPI, pytest (asyncio_mode=auto), tarfile/base64url bundles, Agent Skills spec (SKILL.md). No new dependencies, no new files.

---

## Background — verified scope (grounded in current code, 2026-06-26)

A 6-agent scope-verify workflow read the actual code. Key facts (and where the spec/critique were **stale**):

- **Voice agent on disk** (`kernel/builder/skill_generator.py:151-179`): exactly `agents_dir/<name>/manifest.yaml` + `skill.yaml`. `manifest.yaml` sets `protocol: "skill"` and carries `tools` + `description`. **No SKILL.md.**
- **Export breaks FIRST at discovery, not the packager.** `GET /skills/{name}/export` (`kernel/main.py:2121-2146`) resolves via `_get_skills_registry().get(name)`. `SkillsRegistry` sources are `%APPDATA%/KALI/skills` + builtin `skills/` only — **never `agents_dir`** (`kernel/skills/registry.py:79-91`) — and `discover()` skips any dir without SKILL.md (`registry.py:138-140`). So `reg.get(<voice-skill>)` → `None` → `"not found locally"` **before** `package_skill` runs.
- **Packager hard-requires SKILL.md and drops the config** (`kernel/skills/publisher.py:169-180`): `tar.add(skill_dir/"SKILL.md")` is unconditional (→ `FileNotFoundError`), and the tar only ever contains `SKILL.md` + `references/` + `assets/` + `scripts/` — `manifest.yaml`/`skill.yaml` are **never** bundled, so even a fixed install side would receive a non-runnable skill.
- **Receiver requires SKILL.md to install** (`kernel/skills/installer.py:329` → `kernel/skills/loader.py:195-196`): `load_skill(strict=True)` raises `FileNotFoundError` without SKILL.md. ⇒ **A synthesized SKILL.md in the bundle satisfies this with zero installer changes** — the elegance of this plan.
- **`_is_callable` dir mismatch** (`kernel/plugin_registry.py:245-256`): for `protocol=="skill"` it checks `self._agents_dir / name / "skill.yaml"`, but imports land under `%APPDATA%/KALI/skills/<name>`. ⇒ imported skill shows in `/agents` and runs, but is **withheld from the LLM palette**. This is the irreducible registry-reconciliation fix.
- **Spec correction #1 (2d):** the install route already calls `plugin_registry.register_dir(install_path)` + `if (install_path/"skill.yaml").exists(): skill_executor.load_skill(install_path)` for **both** `/skills/install` and `/skills/install-bundle` (`main.py:2104-2112`, verified against `git show 72f5254`). **Do NOT re-add route wiring.**
- **Spec correction #2 (registry approach):** consulting `self._skills[name].skill_dir` alone is **insufficient** — for a manifest.yaml-only voice agent `register_dir` takes the legacy branch and never populates `self._skills`. The robust minimal fix is a `self._dirs[name]` map populated in **both** `discover()` and `register_dir()`.
- **Spec correction #3 (transport):** the envelope (`base64url` `.tar.gz` of a single `<name>/` dir; `GET /skills/{name}/export` → `{status,name,data,size}`; `kali://import?n=&d=`; Rust = pure proxy) is **already consistent** sender↔receiver. Only the bundle **contents** change.
- **Local voice agents are already LLM-callable** (built via `flow.py` `register_dir` under `agents_dir`; `_is_callable` finds `agents_dir/<name>/skill.yaml`). The `self._dirs` change **must preserve** this (it does — `self._dirs.get(name, self._agents_dir/name)`).

**Known constraint (honest-fail, see Open Items):** `validate_frontmatter` (`kernel/skills/validator.py:46-66`) requires `name` to be lowercase-alphanumeric + single hyphens. The voice builder does **not** enforce kebab/lowercase (`skill_generator.py:138` only blocks `/ \ ..`). A voice agent whose name has uppercase / underscore / Cyrillic produces a synthesized SKILL.md that **fails** `load_skill(strict=True)` at install. Phase A returns an **honest error** at export for such names (Task 2b) rather than shipping a bundle that silently fails on import. Fixing name generation in the builder is out of scope (separate follow-up).

---

## File Structure

No new files. Surgical edits to 3 source files + 4 test files.

| File | Change |
|---|---|
| `kernel/plugin_registry.py` | Add `self._dirs: dict[str, Path]`; populate in `discover()` + `register_dir()`; `_is_callable` consults it; add `skill_dir_for(name)` accessor. |
| `kernel/skills/publisher.py` | `package_skill`: synthesize a spec-valid SKILL.md when absent; carry `manifest.yaml` + `skill.yaml`. New module helpers `_read_manifest_meta` + `_synthesize_skill_md`. |
| `kernel/main.py` | `skills_export` handler: fall back to `app.state.plugin_registry.skill_dir_for(name)` when `SkillsRegistry` misses; honest error for non-spec names. |
| `tests/kernel/test_plugin_registry.py` | Registry reconciliation: imported-dir callable, no-`skill.yaml` withheld, local regression, `skill_dir_for`. |
| `tests/kernel/skills/test_publisher.py` | `package_skill` synthesizes SKILL.md + carries config for a voice skill; SKILL.md-skill bundle unchanged (regression). |
| `tests/test_skills_bundle.py` | **Keystone:** voice skill → `package_skill` → `install_from_bundle` → synthesized SKILL.md + skill.yaml on disk → `register_dir` → tool in `get_all_tools` (full Phase A goal, no app boot). |
| `tests/kernel/test_main.py` | Export route returns ok+data for a voice agent via the plugin-registry fallback; existing 2d route test stays green. |

**Test run command (this repo):** `\.venv\Scripts\python.exe -m pytest <files> -q` (full suite fails natively; run focused subsets).

---

## Chunk 1: Registry reconciliation (`_is_callable` by real dir)

Makes an imported (or any out-of-`agents_dir`) `skill.yaml`-backed skill LLM-callable, while preserving the withhold-guard for pure-SKILL.md skills with no `skill.yaml`. Self-contained — ships value alone (closes the 2d-documented GAP).

### Task 1: `self._dirs` map + `_is_callable` consults it + `skill_dir_for` accessor

**Files:**
- Modify: `kernel/plugin_registry.py` (`__init__` ~104-108, `discover` ~146-181, `register_dir` ~213-220, `_is_callable` ~245-256, new accessor)
- Test: `tests/kernel/test_plugin_registry.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/kernel/test_plugin_registry.py` (top-level, uses its own fresh registry so it does not depend on the `registry` fixture's sample dir):

```python
def _write_voice_skill(skill_dir: Path) -> None:
    """A voice-built skill on disk: manifest.yaml + skill.yaml, NO SKILL.md."""
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": skill_dir.name,
                "version": "1.0.0",
                "description": "Track water intake",
                "protocol": "skill",
                "tools": [{"name": "log", "description": "Log a data point", "parameters": {}}],
                "capabilities": [f"{skill_dir.name}.log"],
                "permissions": [],
            }
        )
    )
    (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))


def test_skill_installed_outside_agents_dir_is_callable(tmp_path: Path) -> None:
    """A skill registered from %APPDATA%/KALI/skills (NOT agents_dir) must still
    enter the LLM tool palette — the registry-reconciliation fix."""
    reg = PluginRegistry(tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    install_dir = tmp_path / "appdata_skills" / "water-tracker"
    _write_voice_skill(install_dir)

    assert reg.register_dir(install_dir) is not None
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "water-tracker__log" in tool_names
    assert reg.skill_dir_for("water-tracker") == install_dir


def test_skill_without_skill_yaml_is_withheld(tmp_path: Path) -> None:
    """Withhold-guard preserved: a protocol='skill' manifest with no skill.yaml
    anywhere must NOT be advertised (calling it would yield 'Skill not found')."""
    reg = PluginRegistry(tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    bad = tmp_path / "appdata_skills" / "ghost"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text(
        yaml.dump(
            {
                "name": "ghost", "version": "1.0.0", "description": "no template",
                "protocol": "skill",
                "tools": [{"name": "run", "description": "r", "parameters": {}}],
                "capabilities": ["ghost.run"], "permissions": [],
            }
        )
    )  # deliberately NO skill.yaml

    assert reg.register_dir(bad) is not None  # present in /agents...
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "ghost__run" not in tool_names  # ...but withheld from the LLM
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/test_plugin_registry.py::test_skill_installed_outside_agents_dir_is_callable tests/kernel/test_plugin_registry.py::test_skill_without_skill_yaml_is_withheld -q`
Expected: `test_skill_installed_outside_agents_dir_is_callable` FAILS (`AttributeError: ... 'skill_dir_for'` or the tool missing — `_is_callable` checks `agents_dir/water-tracker/skill.yaml`, which is absent). The withhold test may already pass (no skill.yaml anywhere) — that's fine; it locks the guard.

- [ ] **Step 3: Implement the registry changes** in `kernel/plugin_registry.py`:

`__init__` (after `self._skills` line ~108):
```python
        self._skills: dict[str, SkillManifest] = {}
        # Real source directory of each registered agent/skill, keyed by name.
        # Tracks dirs OUTSIDE agents_dir (imported skills under %APPDATA%/KALI/
        # skills) so _is_callable / export resolve the actual location.
        self._dirs: dict[str, Path] = {}
```

`discover()` — clear the new map alongside the others (~146-147):
```python
        self._agents.clear()
        self._skills.clear()
        self._dirs.clear()
```
and record the dir at the end of the loop, right after `self._agents[manifest.name] = manifest` (~181):
```python
            self._agents[manifest.name] = manifest
            self._dirs[manifest.name] = agent_dir
```

`register_dir()` — record the dir right after `self._agents[manifest.name] = manifest` (~218):
```python
        self._agents[manifest.name] = manifest
        self._dirs[manifest.name] = agent_dir
        logger.info("Registered (incremental): %s v%s", manifest.name, manifest.version)
```

`_is_callable()` — consult the real dir (replace the `return` at ~256):
```python
        if agent.protocol != "skill":
            return True
        skill_dir = self._dirs.get(agent.name, self._agents_dir / agent.name)
        return (skill_dir / "skill.yaml").is_file()
```

Add a public accessor after `get_skill()` (~231):
```python
    def skill_dir_for(self, name: str) -> Path | None:
        """Real source directory of a registered agent/skill, or None.

        Unlike :meth:`get_skill` (SKILL.md skills only), this tracks the dir for
        EVERY registered manifest — including voice-built (manifest.yaml-only)
        and imported skills under %APPDATA%/KALI/skills — so callers (e.g. the
        export route) can resolve a bundle source regardless of format.
        """
        return self._dirs.get(name)
```

- [ ] **Step 4: Run the new tests + the existing registry suite to verify green + no regression**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/test_plugin_registry.py -q`
Expected: PASS, including the pre-existing `test_register_dir_adds_single_skill_live` (skill under `agents_dir` still callable — `self._dirs["water-tracker"]` == `agents_dir/water-tracker`).

- [ ] **Step 5: Commit**

```bash
git add kernel/plugin_registry.py tests/kernel/test_plugin_registry.py
git commit -m "feat(registry): make imported skills LLM-callable by tracking real dir"
```

---

## Chunk 2: Export send-path (synthesize SKILL.md + carry config + registry fallback)

Makes a voice agent exportable as a bundle the **unchanged** receiver accepts and runs.

### Task 2a: `package_skill` synthesizes SKILL.md + carries `manifest.yaml`/`skill.yaml`

**Files:**
- Modify: `kernel/skills/publisher.py` (imports; new helpers; `package_skill` ~144-182)
- Test: `tests/kernel/skills/test_publisher.py`

- [ ] **Step 1: Write the failing test** — append to `tests/kernel/skills/test_publisher.py` (self-contained — build the voice dir inline; the file's own `_make_skill` has a different signature, do **not** reuse it; uses `tarfile` to inspect the bundle):

```python
def test_package_voice_skill_synthesizes_skill_md(tmp_path: Path) -> None:
    """A voice-built skill (manifest.yaml + skill.yaml, no SKILL.md) packages
    into a bundle that carries a synthesized SKILL.md AND the config files."""
    import tarfile
    import yaml as _yaml

    src = tmp_path / "water-tracker"
    src.mkdir()
    (src / "manifest.yaml").write_text(
        _yaml.dump({"name": "water-tracker", "description": "Track water intake daily",
                    "protocol": "skill", "tools": [{"name": "log"}]})
    )
    (src / "skill.yaml").write_text(_yaml.dump({"template": "tracker", "config": {}}))

    bundle = package_skill(src, output_dir=tmp_path / "out")
    with tarfile.open(bundle, "r:gz") as tar:
        names = set(tar.getnames())
    assert "water-tracker/SKILL.md" in names      # synthesized
    assert "water-tracker/manifest.yaml" in names  # carried (registry + tools)
    assert "water-tracker/skill.yaml" in names     # carried (runnable)
```

- [ ] **Step 2: Run to verify it fails**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/skills/test_publisher.py::test_package_voice_skill_synthesizes_skill_md -q`
Expected: FAIL with `FileNotFoundError: ... SKILL.md` (the unconditional `tar.add(skill_dir/"SKILL.md")`).

- [ ] **Step 3: Implement** in `kernel/skills/publisher.py`. Add **only the two missing imports** — `tarfile`/`tempfile`/`shutil` are already imported, do **NOT** re-add them (ruff `F811`, which this plan's own verification step catches): add `import io` (alphabetical, just before `import logging`, ~line 21) and `import yaml` (after the stdlib block, before the `from kernel...` imports — matches `loader.py`/`registry.py` ordering).

Add module-level helpers (above `package_skill`):
```python
def _read_manifest_meta(skill_dir: Path) -> str:
    """Best-effort description from manifest.yaml / skill.yaml (voice skills)."""
    for fname in ("manifest.yaml", "skill.yaml"):
        fpath = skill_dir / fname
        if fpath.is_file():
            try:
                data = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if isinstance(data, dict) and data.get("description"):
                return str(data["description"])
    return ""


def _synthesize_skill_md(skill_dir: Path) -> bytes:
    """Build a minimal, spec-valid SKILL.md for a voice skill that ships only
    manifest.yaml + skill.yaml. The frontmatter ``name`` is the directory name so
    the receiver's ``load_skill(expected_name=dir)`` validates after extraction.
    """
    name = skill_dir.name
    description = _read_manifest_meta(skill_dir).strip()
    if not description:
        description = f"{name}: agent created in KALI by voice."
    description = description[:1024]  # spec cap — keep load_skill(strict=True) valid on import
    frontmatter = {"name": name, "description": description, "compatibility": "protocol=skill"}
    yaml_text = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).rstrip()
    body = f"# {name}\n\n{description}\n\n_Generated by the KALI voice builder._\n"
    return f"---\n{yaml_text}\n---\n\n{body}".encode("utf-8")
```
Add a third module-level helper `_add_bundle_members` — it **gates** the config-carry to the no-SKILL.md (voice) branch so genuine SKILL.md bundles stay byte-identical, and keeps `package_skill` under the 50-line rule:
```python
def _add_bundle_members(
    tar: tarfile.TarFile, skill_dir: Path, *, include_scripts: bool
) -> None:
    """Add a skill's files to an open tarball under the ``<name>/`` arcname.

    SKILL.md-based skills are packaged exactly as before. Voice-built skills
    (no SKILL.md) get a synthesized SKILL.md plus their manifest.yaml/skill.yaml
    so the imported skill is both spec-valid and runnable.
    """
    name = skill_dir.name
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        tar.add(skill_md, arcname=f"{name}/SKILL.md")
    else:
        # Voice-built skills ship manifest.yaml + skill.yaml without a SKILL.md;
        # synthesize a spec-valid one so the existing SKILL.md loader/validator
        # accept the imported bundle (zero installer change), and carry the
        # config so it stays runnable (SkillExecutor reads skill.yaml; the
        # registry reads manifest.yaml). Gated here so SKILL.md publishes are
        # byte-identical to today.
        content = _synthesize_skill_md(skill_dir)
        info = tarfile.TarInfo(name=f"{name}/SKILL.md")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
        for fname in ("manifest.yaml", "skill.yaml"):
            fpath = skill_dir / fname
            if fpath.is_file():
                tar.add(fpath, arcname=f"{name}/{fname}")

    for subdir in ("references", "assets"):
        src = skill_dir / subdir
        if src.is_dir():
            tar.add(src, arcname=f"{name}/{subdir}")

    if include_scripts:
        scripts = skill_dir / "scripts"
        if scripts.is_dir():
            tar.add(scripts, arcname=f"{name}/scripts")
```
Then replace the tar-building block in `package_skill` (~168-182, the `with tarfile.open(...)` block **and** its trailing `return bundle_path`) with a single call:
```python
    # Build the tarball: everything under skill_dir → arcname skill_dir.name/*
    with tarfile.open(bundle_path, "w:gz") as tar:
        _add_bundle_members(tar, skill_dir, include_scripts=include_scripts)

    return bundle_path
```
Update the `package_skill` docstring line `skill_dir: Source skill dir (must contain SKILL.md).` → `Source skill dir (SKILL.md synthesized from manifest.yaml if absent).`

- [ ] **Step 4: Run the new test + the full publisher suite (regression: SKILL.md-only bundles unchanged)**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/skills/test_publisher.py -q`
Expected: PASS, including the existing `test_excludes_scripts_if_flagged` namelist assertion (a pure-SKILL.md fixture has no `manifest.yaml`/`skill.yaml`, so its namelist is unchanged).

- [ ] **Step 5: Commit**

```bash
git add kernel/skills/publisher.py tests/kernel/skills/test_publisher.py
git commit -m "feat(share): package voice-built skills (synthesize SKILL.md + carry config)"
```

### Task 2b: export route falls back to the plugin registry + honest non-spec-name error

**Files:**
- Modify: `kernel/main.py` (`skills_export` ~2133-2143)
- Test: `tests/kernel/test_main.py`

- [ ] **Step 1: Write the failing route test** — append to `tests/kernel/test_main.py` (reuses the `app`/`client` fixtures at lines 36-56):

```python
class TestExportVoiceAgent:
    """A voice-built agent (manifest.yaml + skill.yaml, no SKILL.md) under
    agents_dir is exportable via the plugin-registry fallback (Phase A)."""

    async def test_export_voice_agent_returns_bundle(
        self, app, client: AsyncClient, tmp_path: Path
    ) -> None:
        import base64

        skill_dir = app.state.plugin_registry.agents_dir / "water-tracker"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "manifest.yaml").write_text(
            yaml.dump({"name": "water-tracker", "version": "1.0.0",
                       "description": "Track water intake daily", "protocol": "skill",
                       "tools": [{"name": "log", "description": "Log", "parameters": {}}],
                       "capabilities": ["water-tracker.log"], "permissions": []})
        )
        (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))
        app.state.plugin_registry.register_dir(skill_dir)

        resp = await client.get("/skills/water-tracker/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok", body
        assert isinstance(body["data"], str) and body["data"]
        # round-trips: decodes to a gzip tar (smoke check)
        raw = base64.urlsafe_b64decode(body["data"] + "=" * (-len(body["data"]) % 4))
        assert raw[:2] == b"\x1f\x8b"  # gzip magic
```

- [ ] **Step 2: Run to verify it fails**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/test_main.py::TestExportVoiceAgent -q`
Expected: FAIL — `body["status"] == "error"` (`"Skill 'water-tracker' not found locally"`), because `SkillsRegistry` has no `agents_dir` source.

- [ ] **Step 3: Implement the fallback** in `kernel/main.py` `skills_export`. Add `from kernel.skills.validator import validate_frontmatter` to the handler's local imports. Then **replace the whole body from line 2133 through line 2143** — the `reg.get` resolution **and** the existing `try/except` package call (line 2140's `package_skill(skill.skill_dir, ...)` **must** become `package_skill(skill_dir, ...)`; on the fallback path `skill` is `None`, so leaving `skill.skill_dir` raises `AttributeError`) — with:
```python
        reg = _get_skills_registry()
        skill = reg.get(name)
        if skill is not None:
            skill_dir = skill.skill_dir
        else:
            # Voice-built agents live under agents_dir (manifest.yaml + skill.yaml,
            # no SKILL.md) and aren't indexed by SkillsRegistry; the live plugin
            # registry tracks every agent's real directory (Phase A share fix).
            skill_dir = app.state.plugin_registry.skill_dir_for(name)
        if skill_dir is None:
            return {"status": "error", "message": f"Skill '{name}' not found locally"}

        # Honest-fail: a non-spec name (uppercase / underscore / non-ascii — the
        # voice builder's slugify uses \w without re.ASCII, so Cyrillic survives)
        # would synthesize a SKILL.md the receiver's strict loader rejects on
        # import. Refuse here rather than ship a bundle that dies on the friend.
        if not validate_frontmatter({"name": name, "description": "x"}, expected_name=name).valid:
            return {
                "status": "error",
                "message": (
                    f"Agent name '{name}' can't be shared yet — names must be "
                    "lowercase latin letters, digits and single hyphens."
                ),
            }

        try:
            with tempfile.TemporaryDirectory() as tmp:
                bundle = package_skill(skill_dir, output_dir=Path(tmp))
                raw = bundle.read_bytes()
        except Exception as exc:
            return {"status": "error", "message": f"Export failed: {exc}"}
```
(The trailing `data = base64.urlsafe_b64encode(raw).decode().rstrip("=")` and `return {"status": "ok", ...}` lines, ~2145-2146, are unchanged.)

- [ ] **Step 4: Run the new test + the existing install-bundle route test (regression)**

Run: `\.venv\Scripts\python.exe -m pytest tests/kernel/test_main.py::TestExportVoiceAgent tests/kernel/test_main.py::TestInstallBundleRegistersLive -q`
Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add kernel/main.py tests/kernel/test_main.py
git commit -m "feat(share): export voice-built agents via plugin-registry fallback"
```

---

## Chunk 3: End-to-end keystone + regression sweep

Proves the entire Phase A goal in one function-level test (no app boot, no `%APPDATA%` pollution), then runs the affected suites together.

### Task 3: Keystone round-trip — voice skill → bundle → import → LLM-callable

**Files:**
- Test: `tests/test_skills_bundle.py` (add helper + keystone test)

- [ ] **Step 1: Write the keystone test** — append to `tests/test_skills_bundle.py`:

```python
def _make_voice_skill(root: Path, name: str = "water-tracker") -> Path:
    """A voice-built skill: manifest.yaml + skill.yaml, NO SKILL.md."""
    import yaml
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.yaml").write_text(
        yaml.dump({"name": name, "version": "1.0.0", "description": "Track water intake daily",
                   "protocol": "skill",
                   "tools": [{"name": "log", "description": "Log a data point", "parameters": {}}],
                   "capabilities": [f"{name}.log"], "permissions": []})
    )
    (skill_dir / "skill.yaml").write_text(yaml.dump({"template": "tracker", "config": {}}))
    return skill_dir


def test_voice_skill_roundtrip_is_llm_callable(tmp_path: Path) -> None:
    """The full Phase A promise: a voice-built agent exports, installs on a
    friend's device (synthesized SKILL.md passes the strict loader, config
    carried), and is offered to the LLM."""
    from kernel.plugin_registry import PluginRegistry

    src = _make_voice_skill(tmp_path / "src")
    data = _bundle_b64(src, tmp_path / "out")

    installed = tmp_path / "installed"
    result = install_from_bundle(data, target_dir=installed)
    assert result.ok, result.error
    assert (installed / "water-tracker" / "SKILL.md").is_file()    # synthesized
    assert (installed / "water-tracker" / "skill.yaml").is_file()  # carried

    # The imported skill is LLM-callable from its install dir (registry reconcile)
    reg = PluginRegistry(tmp_path / "agents")
    (tmp_path / "agents").mkdir()
    reg.register_dir(installed / "water-tracker")
    tool_names = {t["function"]["name"] for t in reg.get_all_tools()}
    assert "water-tracker__log" in tool_names
```

- [ ] **Step 2: Run the keystone test**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_skills_bundle.py::test_voice_skill_roundtrip_is_llm_callable -q`
Expected: PASS (Chunks 1+2 already make every leg work). If it FAILS, the failing leg points at the gap — fix in the relevant chunk, do not patch the test.

- [ ] **Step 3: Run the full affected suite (regression sweep)**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_skills_bundle.py tests/kernel/skills/test_publisher.py tests/kernel/test_plugin_registry.py tests/kernel/test_main.py -q`
Expected: all PASS. (If `tests/kernel/test_main.py` is slow/boots ML, it is acceptable to run it separately; the keystone + registry + publisher tests are fast.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_skills_bundle.py
git commit -m "test(share): end-to-end voice-skill P2P round-trip is LLM-callable"
```

---

## Verification before completion

- [ ] `\.venv\Scripts\python.exe -m pytest tests/test_skills_bundle.py tests/kernel/skills/test_publisher.py tests/kernel/test_plugin_registry.py -q` → all green (fast core).
- [ ] `\.venv\Scripts\python.exe -m pytest tests/kernel/test_main.py -q` → green (route surface incl. 2d regression).
- [ ] `\.venv\Scripts\python.exe -m ruff check kernel/plugin_registry.py kernel/skills/publisher.py kernel/main.py` → clean.
- [ ] Manual reasoning trace recorded: imported skill (SKILL.md+manifest.yaml+skill.yaml) → `register_dir` → `protocol='skill'` → `_is_callable` via `self._dirs[name]/skill.yaml` (install dir) → in `get_all_tools`. Local voice agent (no SKILL.md, agents_dir) → unchanged callable. Pure-SKILL.md no-skill.yaml → still withheld.
- [ ] **Live-verify (per [[feedback-quality-live-verify]]):** after the installer is next rebuilt, on the running app: voice-build an agent → Share → import on a second profile/device → confirm it appears in Мастерская/Мои **and** the LLM executes its tool (not just listed). (Installer rebuild is a separate step; this plan is code-only.)

## Open items / risks (surface to Vasily; not decided here)

1. **Non-spec agent names** — handled as honest-fail at export (Task 2b). The deeper fix (slugify/transliterate names in `skill_generator`/`extractor` so Russian voice input yields kebab-ascii names) is a **separate builder task**; without it, some voice agents simply can't be shared until renamed. Flag for a follow-up.
2. **`scripts/` in voice bundles** — voice skills have no `scripts/`, so the AST safety gate has nothing to scan on import (a template-only skill is data, not code). Consistent with Phase A scope; Phase C moderation must also review prose/templates (already noted in the spec §C caveat).
3. **`.kali-agent` (pack_agent) path** is a separate older mechanism (`main.py` ~1862) — **not touched**; Phase A consolidates on `/skills/{name}/export`. `.kali-agent` zip is Phase B's catalog format (per spec §5A).
4. **Stale GAP comments** — `kernel/main.py:2034-2038` and `:2099-2103` document the `_is_callable` mismatch as unfixed. Once Chunk 1 lands they are inaccurate; updating/removing them is a tiny optional cleanup (left out to keep the diff surgical — call if wanted).

---

**Plan complete.** Code-only, no new files, no new deps; receiver/transport untouched; crown jewels (withhold-guard, rollback, hardened extraction) preserved. Ready for adversarial review → Vasily approval → TDD execution.
