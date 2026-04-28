//! On-disk JSON cache for the remote catalog index.
//!
//! Mirrors `kernel/skills/catalog.py::_load_cached/_save_cached`. One
//! file per source (`<cache_dir>/<source_id>.json`), TTL-gated by a
//! `cached_at` epoch field. Returning `None` from `load()` covers all
//! "cache miss" cases (file missing, TTL expired, parse error) so the
//! caller's logic is simple: cache hit or fetch.
//!
//! Default cache dir uses `dirs::cache_dir()` — `%LOCALAPPDATA%/kali`
//! on Windows, `~/.cache/kali` on Linux, `~/Library/Caches/kali` on
//! macOS. Override with `KALI_CATALOG_CACHE_DIR` for tests or
//! frozen-install layouts.

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use tracing::warn;

use crate::backend::skills::catalog::CatalogEntry;

/// Default catalog-cache TTL in seconds. Matches Python's
/// `SkillsCatalog.CACHE_TTL` (3600 = 1 hour).
pub const DEFAULT_TTL_SECONDS: u64 = 3600;

/// Cache file payload — wraps the entries list with the timestamp the
/// load step compares against the TTL.
#[derive(Debug, Serialize, Deserialize)]
struct CacheFile {
    cached_at: f64,
    entries: Vec<CatalogEntry>,
}

/// Resolve the catalog cache directory. Honors
/// `KALI_CATALOG_CACHE_DIR` env override; otherwise places under the
/// platform cache dir.
pub fn default_cache_dir() -> Result<PathBuf> {
    if let Ok(p) = std::env::var("KALI_CATALOG_CACHE_DIR") {
        return Ok(PathBuf::from(p));
    }
    let base = dirs::cache_dir()
        .context("no platform cache dir available — set KALI_CATALOG_CACHE_DIR")?;
    Ok(base.join("kali").join("catalog-cache"))
}

/// Ensure the directory exists; idempotent.
pub fn ensure_cache_dir(dir: &Path) -> Result<()> {
    std::fs::create_dir_all(dir)
        .with_context(|| format!("create catalog cache dir at {:?}", dir))
}

fn cache_file_for(dir: &Path, source_id: &str) -> PathBuf {
    dir.join(format!("{source_id}.json"))
}

fn now_seconds() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

/// Read the cache for `source_id`, returning the entries iff the file
/// exists, parses, and is within TTL. Anything else → `None`.
pub fn load(dir: &Path, source_id: &str, ttl_seconds: u64) -> Option<Vec<CatalogEntry>> {
    let path = cache_file_for(dir, source_id);
    if !path.is_file() {
        return None;
    }
    let raw = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(err) => {
            warn!(?err, ?path, "catalog cache: read failed");
            return None;
        }
    };
    let parsed: CacheFile = match serde_json::from_str(&raw) {
        Ok(f) => f,
        Err(err) => {
            warn!(?err, ?path, "catalog cache: parse failed");
            return None;
        }
    };
    let age = now_seconds() - parsed.cached_at;
    if age > ttl_seconds as f64 {
        return None;
    }
    Some(parsed.entries)
}

/// Write `entries` to the cache file for `source_id`. Overwrites any
/// existing file. Errors are logged but not propagated — a failed
/// cache write is a performance regression, not a correctness issue.
pub fn save(dir: &Path, source_id: &str, entries: &[CatalogEntry]) {
    let path = cache_file_for(dir, source_id);
    let payload = CacheFile {
        cached_at: now_seconds(),
        entries: entries.to_vec(),
    };
    let raw = match serde_json::to_string(&payload) {
        Ok(s) => s,
        Err(err) => {
            warn!(?err, source = source_id, "catalog cache: serialise failed");
            return;
        }
    };
    if let Err(err) = std::fs::write(&path, raw) {
        warn!(?err, ?path, "catalog cache: write failed");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::skills::catalog::CatalogEntry;
    use std::collections::BTreeMap;
    use tempfile::tempdir;

    fn sample_entry(name: &str) -> CatalogEntry {
        CatalogEntry {
            name: name.into(),
            description: format!("desc for {name}"),
            source_id: "test".into(),
            source_label: "Test".into(),
            trust: "community".into(),
            repo_owner: "owner".into(),
            repo_name: "repo".into(),
            repo_ref: "main".into(),
            skill_path: format!("skills/{name}"),
            license: None,
            compatibility: None,
            metadata: serde_json::Value::Object(serde_json::Map::new()),
        }
    }

    #[test]
    fn load_returns_none_when_file_missing() {
        let temp = tempdir().unwrap();
        assert!(load(temp.path(), "absent", DEFAULT_TTL_SECONDS).is_none());
    }

    #[test]
    fn save_then_load_round_trips_within_ttl() {
        let temp = tempdir().unwrap();
        let entries = vec![sample_entry("a"), sample_entry("b")];
        save(temp.path(), "src", &entries);
        let loaded = load(temp.path(), "src", DEFAULT_TTL_SECONDS).expect("hit");
        assert_eq!(loaded.len(), 2);
        assert_eq!(loaded[0].name, "a");
        assert_eq!(loaded[1].skill_path, "skills/b");
    }

    #[test]
    fn load_returns_none_when_entry_expired() {
        let temp = tempdir().unwrap();
        let entries = vec![sample_entry("x")];
        save(temp.path(), "src", &entries);
        // TTL = 0 forces immediate expiry.
        assert!(load(temp.path(), "src", 0).is_none());
    }

    #[test]
    fn load_returns_none_on_parse_error() {
        let temp = tempdir().unwrap();
        let path = temp.path().join("broken.json");
        std::fs::write(&path, "not valid json").unwrap();
        assert!(load(temp.path(), "broken", DEFAULT_TTL_SECONDS).is_none());
    }

    // Suppress unused-import warning if BTreeMap isn't referenced
    // elsewhere — keep available for richer fixtures later.
    #[allow(dead_code)]
    fn _unused(_: BTreeMap<String, String>) {}
}
