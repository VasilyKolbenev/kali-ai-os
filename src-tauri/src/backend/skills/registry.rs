//! In-memory registry of locally-discovered skills.
//!
//! Mirrors `kernel/skills/registry.py::SkillsRegistry`. Holds an
//! `Arc<RwLock<HashMap>>` so the HTTP layer can read concurrently
//! without blocking discovery; `reload()` is a write that swaps the
//! whole map.
//!
//! ## Source priority
//!
//! Sources are processed in REVERSE order so that earlier-listed
//! sources overwrite later ones on name collision — i.e. user wins
//! over builtin. Matches Python's invariant.
//!
//! ## Discovery semantics
//!
//! - Top-level `<source.path>/<skill_name>/SKILL.md` only. No deep
//!   recursion — keeps surface predictable and prevents accidental
//!   discovery of skill assets that happen to be named SKILL.md.
//! - Malformed SKILL.md files are logged at WARN and skipped, not
//!   propagated as errors. One bad skill mustn't take down discovery
//!   of the rest.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::RwLock;

use anyhow::{Context, Result};
use tracing::{info, warn};

use crate::backend::skills::loader::{load_skill, SkillManifest};

/// Root directory holding skill subfolders. Mirrors Python's
/// `SkillSource` dataclass.
#[derive(Debug, Clone)]
pub struct SkillSource {
    pub name: String,
    pub path: PathBuf,
    pub read_only: bool,
}

/// Discovered-skills registry. Cheap to share via `Arc` — handlers
/// take an `Arc<SkillsRegistry>` and call `list_all()` lock-free
/// (each call clones the manifest list under the read lock).
pub struct SkillsRegistry {
    sources: Vec<SkillSource>,
    skills: RwLock<HashMap<String, SkillManifest>>,
}

impl SkillsRegistry {
    pub fn new(sources: Vec<SkillSource>) -> Self {
        Self {
            sources,
            skills: RwLock::new(HashMap::new()),
        }
    }

    pub fn sources(&self) -> &[SkillSource] {
        &self.sources
    }

    /// Walk every source, parse every SKILL.md, build the index.
    /// Idempotent — call again to refresh after install/uninstall.
    pub fn discover(&self) -> Result<()> {
        let mut new_index: HashMap<String, SkillManifest> = HashMap::new();

        // Reverse so first-priority sources are processed last and
        // their entries win on name collision.
        for source in self.sources.iter().rev() {
            if !source.path.is_dir() {
                continue;
            }
            let entries = match std::fs::read_dir(&source.path) {
                Ok(e) => e,
                Err(err) => {
                    warn!(
                        source = %source.name,
                        path = ?source.path,
                        ?err,
                        "skipping unreadable skill source"
                    );
                    continue;
                }
            };
            for entry in entries.flatten() {
                let dir = entry.path();
                if !dir.is_dir() {
                    continue;
                }
                let skill_md = dir.join("SKILL.md");
                if !skill_md.is_file() {
                    continue;
                }
                match load_skill(&dir, &source.name) {
                    Ok(manifest) => {
                        new_index.insert(manifest.name.clone(), manifest);
                    }
                    Err(err) => {
                        warn!(
                            source = %source.name,
                            dir = ?dir,
                            ?err,
                            "skipping malformed skill"
                        );
                    }
                }
            }
        }

        let count = new_index.len();
        let source_count = self.sources.len();
        let mut guard = self
            .skills
            .write()
            .map_err(|_| anyhow::anyhow!("skills index lock poisoned"))?;
        *guard = new_index;
        drop(guard);
        info!(skills = count, sources = source_count, "skills registry rebuilt");
        Ok(())
    }

    /// All discovered skills, sorted by name. Returns owned clones so
    /// callers don't hold the read lock; the cost is acceptable at
    /// `/skills/installed` cadence (interactive only).
    pub fn list_all(&self) -> Vec<SkillManifest> {
        let guard = match self.skills.read() {
            Ok(g) => g,
            Err(poison) => poison.into_inner(),
        };
        let mut all: Vec<SkillManifest> = guard.values().cloned().collect();
        all.sort_by(|a, b| a.name.cmp(&b.name));
        all
    }

    /// Single-skill lookup. Returns `None` if missing.
    pub fn get(&self, name: &str) -> Option<SkillManifest> {
        let guard = match self.skills.read() {
            Ok(g) => g,
            Err(poison) => poison.into_inner(),
        };
        guard.get(name).cloned()
    }

    /// Idempotent re-discovery. After install/uninstall, callers must
    /// invoke this to refresh the cache.
    pub fn reload(&self) -> Result<()> {
        self.discover()
    }
}

/// Build the default source list for the running backend. User skills
/// take precedence over builtin (matches Python). Paths are
/// configurable via env vars so tests + frozen installs + dev shells
/// can each point at the right directories.
pub fn default_sources() -> Result<Vec<SkillSource>> {
    let user_dir = resolve_user_skills_dir().context("resolve user skills dir")?;
    if !user_dir.exists() {
        std::fs::create_dir_all(&user_dir)
            .with_context(|| format!("create user skills dir at {:?}", user_dir))?;
    }

    let builtin_dir = resolve_builtin_skills_dir().context("resolve builtin skills dir")?;

    let mut sources = vec![SkillSource {
        name: "user".into(),
        path: user_dir,
        read_only: false,
    }];
    if builtin_dir.is_dir() {
        sources.push(SkillSource {
            name: "builtin".into(),
            path: builtin_dir,
            read_only: true,
        });
    }
    Ok(sources)
}

fn resolve_user_skills_dir() -> Result<PathBuf> {
    if let Ok(p) = std::env::var("KALI_USER_SKILLS_DIR") {
        return Ok(PathBuf::from(p));
    }
    // %APPDATA%/KALI/skills on Windows; XDG data dir elsewhere.
    let base = dirs::data_dir().ok_or_else(|| {
        anyhow::anyhow!("no platform data dir available — set KALI_USER_SKILLS_DIR")
    })?;
    Ok(base.join("KALI").join("skills"))
}

fn resolve_builtin_skills_dir() -> Result<PathBuf> {
    if let Ok(p) = std::env::var("KALI_BUILTIN_SKILLS_DIR") {
        return Ok(PathBuf::from(p));
    }
    // Dev mode: backend runs from `src-tauri/`, project root is `..`.
    // Builtin SKILL.md files live in `agents/` per the existing repo
    // layout (Python's `_legacy_agents_dir` matches). When a frozen
    // installer is built later, override via the env var.
    Ok(PathBuf::from("../agents"))
}

