//! Remote skills catalog — aggregates SKILL.md indexes from public
//! GitHub registries (and JSON aggregator endpoints) with on-disk
//! caching.
//!
//! Mirrors `kernel/skills/catalog.py` byte-for-byte where possible —
//! the Rust port owns the same data shapes (`CatalogSource`,
//! `CatalogEntry`), the same HTTP API contract, the same TTL-gated
//! cache file layout (one JSON per source under
//! [`super::cache::default_cache_dir`]). UI doesn't notice which side
//! served the response.
//!
//! ## Source types
//!
//! - `github` (default) — list `/repos/{owner}/{repo}/git/trees/{ref}?recursive=1`,
//!   filter to paths ending in `/SKILL.md`, fetch each via raw URL,
//!   parse frontmatter into a [`CatalogEntry`].
//! - `aggregator_json` — fetch a pre-indexed JSON list from
//!   `api_url`. Each item must carry `owner`, `repo`, `name`,
//!   `description` at minimum.
//!
//! ## HTTP base URLs
//!
//! Default to public GitHub, override via `KALI_GITHUB_API_URL` and
//! `KALI_GITHUB_RAW_URL` (used by integration tests pointing at a
//! mock axum server).
//!
//! ## Concurrency
//!
//! `CatalogClient` is `Send + Sync`. Internal entries map is wrapped
//! in `tokio::sync::RwLock`. Reads (list/search/get) are non-blocking
//! and lock-free against refreshes; writes (refresh) take the write
//! lock briefly to swap the source's vector.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;
use tokio::sync::RwLock;
use tracing::{info, warn};

use crate::backend::skills::cache;
use crate::backend::skills::loader::Frontmatter;

const DEFAULT_HTTP_TIMEOUT_SECS: u64 = 15;
const DEFAULT_GITHUB_API_URL: &str = "https://api.github.com";
const DEFAULT_GITHUB_RAW_URL: &str = "https://raw.githubusercontent.com";

/// Configuration for one remote skills registry. Mirrors Python
/// `CatalogSource` dataclass.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogSource {
    pub id: String,
    pub label: String,
    #[serde(default)]
    pub owner: String,
    #[serde(default)]
    pub repo: String,
    #[serde(default = "default_ref")]
    #[serde(rename = "ref")]
    pub git_ref: String,
    #[serde(default = "default_skills_path")]
    pub skills_path: String,
    #[serde(default = "default_trust")]
    pub trust: String,
    #[serde(default = "default_source_type")]
    pub source_type: String,
    #[serde(default)]
    pub api_url: Option<String>,
}

fn default_ref() -> String {
    "main".into()
}
fn default_skills_path() -> String {
    "skills".into()
}
fn default_trust() -> String {
    "community".into()
}
fn default_source_type() -> String {
    "github".into()
}

impl CatalogSource {
    /// Mirrors Python's `display_url` property — used as the human-readable
    /// pointer in the `/skills/catalog/sources` response.
    pub fn display_url(&self) -> String {
        if self.source_type == "aggregator_json" {
            if let Some(url) = &self.api_url {
                return url.clone();
            }
        }
        format!("https://github.com/{}/{}", self.owner, self.repo)
    }

    pub fn to_summary_json(&self) -> Value {
        json!({
            "id": self.id,
            "label": self.label,
            "trust": self.trust,
            "owner": self.owner,
            "repo": self.repo,
            "ref": self.git_ref,
            "url": self.display_url(),
        })
    }
}

/// One indexed skill in a remote source — lightweight (no body).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogEntry {
    pub name: String,
    pub description: String,
    pub source_id: String,
    pub source_label: String,
    pub trust: String,
    pub repo_owner: String,
    pub repo_name: String,
    pub repo_ref: String,
    pub skill_path: String,
    #[serde(default)]
    pub license: Option<String>,
    #[serde(default)]
    pub compatibility: Option<String>,
    #[serde(default)]
    pub metadata: Value,
}

impl CatalogEntry {
    pub fn raw_skill_md_url(&self) -> String {
        format!(
            "https://raw.githubusercontent.com/{}/{}/{}/{}/SKILL.md",
            self.repo_owner, self.repo_name, self.repo_ref, self.skill_path
        )
    }

    pub fn web_url(&self) -> String {
        format!(
            "https://github.com/{}/{}/tree/{}/{}",
            self.repo_owner, self.repo_name, self.repo_ref, self.skill_path
        )
    }

    /// Mirrors Python's `to_dict` — adds derived URLs to the base
    /// fields. UI consumes this shape directly.
    pub fn to_json(&self) -> Value {
        json!({
            "name": self.name,
            "description": self.description,
            "source_id": self.source_id,
            "source_label": self.source_label,
            "trust": self.trust,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "repo_ref": self.repo_ref,
            "skill_path": self.skill_path,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": self.metadata,
            "raw_skill_md_url": self.raw_skill_md_url(),
            "web_url": self.web_url(),
        })
    }
}

/// Errors specific to remote catalog operations. Kept distinct from
/// `anyhow::Error` so callers can map rate-limit (403) failures into
/// a UI-friendly message instead of a generic 500.
///
/// Note: field named `src` rather than `source` to avoid thiserror's
/// `std::error::Error::source()` derivation magic, which expects a
/// nested `dyn Error` and chokes on `String`.
#[derive(Debug, Error)]
pub enum CatalogFetchError {
    #[error("network error for {src}: {message}")]
    Network { src: String, message: String },
    #[error("repo not found: {url}")]
    NotFound { url: String },
    #[error("GitHub API rate-limited for {src}. Set GITHUB_TOKEN to raise quota")]
    RateLimited { src: String },
    #[error("GitHub API error {status} for {src}: {body}")]
    HttpStatus {
        src: String,
        status: u16,
        body: String,
    },
    #[error("aggregator source {src} missing api_url")]
    MissingApiUrl { src: String },
    #[error("invalid JSON from {src}: {message}")]
    InvalidJson { src: String, message: String },
}

/// Default sources — same five Python ships. Kept hardcoded for now;
/// when the YAML override path lands (Phase 4 polish), swap in
/// config-loaded sources here.
pub fn default_sources() -> Vec<CatalogSource> {
    vec![
        CatalogSource {
            id: "anthropic".into(),
            label: "Anthropic Official".into(),
            owner: "anthropics".into(),
            repo: "skills".into(),
            git_ref: default_ref(),
            skills_path: default_skills_path(),
            trust: "official".into(),
            source_type: "github".into(),
            api_url: None,
        },
        CatalogSource {
            id: "microsoft".into(),
            label: "Microsoft Azure".into(),
            owner: "microsoft".into(),
            repo: "skills".into(),
            git_ref: default_ref(),
            skills_path: "skills".into(),
            trust: "official".into(),
            source_type: "github".into(),
            api_url: None,
        },
        CatalogSource {
            id: "voltagent".into(),
            label: "VoltAgent Community".into(),
            owner: "VoltAgent".into(),
            repo: "awesome-agent-skills".into(),
            git_ref: default_ref(),
            skills_path: "skills".into(),
            trust: "community".into(),
            source_type: "github".into(),
            api_url: None,
        },
        CatalogSource {
            id: "kali".into(),
            label: "KALI Skills".into(),
            owner: "VasilyKolbenev".into(),
            repo: "kali-skills".into(),
            git_ref: default_ref(),
            skills_path: default_skills_path(),
            trust: "verified".into(),
            source_type: "github".into(),
            api_url: None,
        },
        CatalogSource {
            id: "neuraldeep".into(),
            label: "NeuralDeep (RU)".into(),
            owner: String::new(),
            repo: String::new(),
            git_ref: default_ref(),
            skills_path: default_skills_path(),
            trust: "community".into(),
            source_type: "aggregator_json".into(),
            api_url: Some("https://neuraldeep.ru/api/skills".into()),
        },
    ]
}

/// Aggregates remote catalogs with on-disk caching.
pub struct CatalogClient {
    sources: Vec<CatalogSource>,
    cache_dir: PathBuf,
    http: reqwest::Client,
    api_base: String,
    raw_base: String,
    cache_ttl_seconds: u64,
    entries: RwLock<HashMap<String, Vec<CatalogEntry>>>,
}

/// Construction parameters. Use `default()` for the production paths;
/// tests pass mock URLs.
pub struct CatalogClientOpts {
    pub sources: Vec<CatalogSource>,
    pub cache_dir: PathBuf,
    pub api_base: String,
    pub raw_base: String,
    pub http_timeout: Duration,
    pub cache_ttl_seconds: u64,
}

impl CatalogClientOpts {
    pub fn defaults() -> Result<Self> {
        let cache_dir = cache::default_cache_dir().context("resolve catalog cache dir")?;
        Ok(Self {
            sources: default_sources(),
            cache_dir,
            api_base: std::env::var("KALI_GITHUB_API_URL")
                .unwrap_or_else(|_| DEFAULT_GITHUB_API_URL.into()),
            raw_base: std::env::var("KALI_GITHUB_RAW_URL")
                .unwrap_or_else(|_| DEFAULT_GITHUB_RAW_URL.into()),
            http_timeout: Duration::from_secs(DEFAULT_HTTP_TIMEOUT_SECS),
            cache_ttl_seconds: cache::DEFAULT_TTL_SECONDS,
        })
    }
}

impl CatalogClient {
    pub fn new(opts: CatalogClientOpts) -> Result<Arc<Self>> {
        cache::ensure_cache_dir(&opts.cache_dir)?;
        let http = reqwest::Client::builder()
            .timeout(opts.http_timeout)
            .build()
            .context("build reqwest client")?;
        Ok(Arc::new(Self {
            sources: opts.sources,
            cache_dir: opts.cache_dir,
            http,
            api_base: opts.api_base,
            raw_base: opts.raw_base,
            cache_ttl_seconds: opts.cache_ttl_seconds,
            entries: RwLock::new(HashMap::new()),
        }))
    }

    pub fn sources(&self) -> &[CatalogSource] {
        &self.sources
    }

    /// JSON for `GET /skills/catalog/sources`.
    pub fn sources_summary(&self) -> Value {
        let arr: Vec<Value> = self.sources.iter().map(|s| s.to_summary_json()).collect();
        json!({ "sources": arr })
    }

    /// Refresh one source. If `force` is `false` and a fresh cache
    /// exists, returns it without HTTP. Network failures degrade
    /// gracefully — the previously-loaded entries (or empty vec) are
    /// returned and a warning is logged. Refresh never crashes the
    /// pipeline.
    pub async fn refresh_source(&self, source_id: &str, force: bool) -> Result<Vec<CatalogEntry>> {
        let source = self
            .sources
            .iter()
            .find(|s| s.id == source_id)
            .ok_or_else(|| anyhow!("unknown catalog source: {source_id}"))?
            .clone();

        if !force {
            if let Some(cached) = cache::load(&self.cache_dir, &source.id, self.cache_ttl_seconds)
            {
                self.entries
                    .write()
                    .await
                    .insert(source.id.clone(), cached.clone());
                return Ok(cached);
            }
        }

        let fetched = match self.fetch_source(&source).await {
            Ok(e) => e,
            Err(err) => {
                warn!(source = %source.id, ?err, "catalog refresh failed; keeping previous data");
                return Ok(self
                    .entries
                    .read()
                    .await
                    .get(&source.id)
                    .cloned()
                    .unwrap_or_default());
            }
        };

        cache::save(&self.cache_dir, &source.id, &fetched);
        self.entries
            .write()
            .await
            .insert(source.id.clone(), fetched.clone());
        Ok(fetched)
    }

    /// Refresh all configured sources. Returns the total number of
    /// entries indexed across all sources.
    pub async fn refresh_all(&self, force: bool) -> usize {
        let mut total = 0usize;
        for source in self.sources.iter() {
            match self.refresh_source(&source.id, force).await {
                Ok(entries) => total += entries.len(),
                Err(err) => warn!(source = %source.id, ?err, "refresh_all skipped a source"),
            }
        }
        total
    }

    /// All entries across all sources, sorted by trust tier
    /// (official → verified → community → other) then name.
    pub async fn list_all(&self) -> Vec<CatalogEntry> {
        let guard = self.entries.read().await;
        let mut all: Vec<CatalogEntry> = self
            .sources
            .iter()
            .flat_map(|s| guard.get(&s.id).cloned().unwrap_or_default())
            .collect();
        drop(guard);
        all.sort_by(|a, b| {
            trust_rank(&a.trust)
                .cmp(&trust_rank(&b.trust))
                .then_with(|| a.name.to_lowercase().cmp(&b.name.to_lowercase()))
        });
        all
    }

    /// Entries from a specific source, in original (insertion) order.
    pub async fn list_by_source(&self, source_id: &str) -> Vec<CatalogEntry> {
        self.entries
            .read()
            .await
            .get(source_id)
            .cloned()
            .unwrap_or_default()
    }

    /// Substring search across name + description, case-insensitive.
    /// Empty query returns `list_all()`.
    pub async fn search(&self, query: &str) -> Vec<CatalogEntry> {
        let q = query.trim().to_lowercase();
        if q.is_empty() {
            return self.list_all().await;
        }
        self.list_all()
            .await
            .into_iter()
            .filter(|e| {
                e.name.to_lowercase().contains(&q) || e.description.to_lowercase().contains(&q)
            })
            .collect()
    }

    /// Lookup by source + name. Returns `None` if absent.
    pub async fn get(&self, source_id: &str, name: &str) -> Option<CatalogEntry> {
        self.entries
            .read()
            .await
            .get(source_id)
            .and_then(|v| v.iter().find(|e| e.name == name).cloned())
    }

    // ── HTTP fetchers (private) ───────────────────────────────────

    async fn fetch_source(&self, source: &CatalogSource) -> Result<Vec<CatalogEntry>> {
        match source.source_type.as_str() {
            "aggregator_json" => self.fetch_aggregator_json(source).await,
            _ => self.fetch_github(source).await,
        }
    }

    async fn fetch_github(&self, source: &CatalogSource) -> Result<Vec<CatalogEntry>> {
        info!(source = %source.id, url = %source.display_url(), "fetching catalog");
        let paths = self.github_tree(source).await?;

        let prefix_filter = if source.skills_path.is_empty() {
            String::new()
        } else {
            format!("{}/", source.skills_path.trim_matches('/'))
        };

        let skill_md_paths: Vec<String> = paths
            .into_iter()
            .filter(|p| p.ends_with("/SKILL.md"))
            .filter(|p| prefix_filter.is_empty() || p.starts_with(&prefix_filter))
            .collect();

        let mut entries = Vec::with_capacity(skill_md_paths.len());
        for path in skill_md_paths {
            let content = match self.fetch_skill_md(source, &path).await {
                Some(c) => c,
                None => continue,
            };
            let fm = match parse_frontmatter_only(&content) {
                Some(f) => f,
                None => continue,
            };
            let (Some(name), Some(description)) = (fm.name.clone(), fm.description.clone()) else {
                continue;
            };
            let skill_dir_path = path.trim_end_matches("/SKILL.md").to_string();
            let metadata: Value = fm
                .metadata
                .map(|v| serde_json::to_value(&v).unwrap_or(json!({})))
                .unwrap_or(json!({}));
            entries.push(CatalogEntry {
                name,
                description,
                source_id: source.id.clone(),
                source_label: source.label.clone(),
                trust: source.trust.clone(),
                repo_owner: source.owner.clone(),
                repo_name: source.repo.clone(),
                repo_ref: source.git_ref.clone(),
                skill_path: skill_dir_path,
                license: fm.license,
                compatibility: fm.compatibility,
                metadata,
            });
        }

        info!(source = %source.id, count = entries.len(), "catalog source indexed");
        Ok(entries)
    }

    async fn github_tree(&self, source: &CatalogSource) -> Result<Vec<String>> {
        let url = format!(
            "{}/repos/{}/{}/git/trees/{}?recursive=1",
            self.api_base, source.owner, source.repo, source.git_ref
        );
        let mut req = self
            .http
            .get(&url)
            .header("Accept", "application/vnd.github+json");
        if let Ok(token) = std::env::var("GITHUB_TOKEN") {
            if !token.is_empty() {
                req = req.header("Authorization", format!("Bearer {token}"));
            }
        }
        let resp = req.send().await.map_err(|e| CatalogFetchError::Network {
            src: source.id.clone(),
            message: e.to_string(),
        })?;
        let status = resp.status();
        if status.as_u16() == 404 {
            return Err(CatalogFetchError::NotFound {
                url: source.display_url(),
            }
            .into());
        }
        if status.as_u16() == 403 {
            return Err(CatalogFetchError::RateLimited {
                src: source.id.clone(),
            }
            .into());
        }
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(CatalogFetchError::HttpStatus {
                src: source.id.clone(),
                status: status.as_u16(),
                body: body.chars().take(200).collect(),
            }
            .into());
        }
        let body: GithubTreeResponse =
            resp.json().await.map_err(|e| CatalogFetchError::InvalidJson {
                src: source.id.clone(),
                message: e.to_string(),
            })?;
        Ok(body
            .tree
            .into_iter()
            .filter(|item| item.kind.as_deref() == Some("blob"))
            .map(|item| item.path)
            .collect())
    }

    async fn fetch_skill_md(&self, source: &CatalogSource, skill_path: &str) -> Option<String> {
        let url = format!(
            "{}/{}/{}/{}/{}",
            self.raw_base, source.owner, source.repo, source.git_ref, skill_path
        );
        match self.http.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => resp.text().await.ok(),
            Ok(resp) => {
                warn!(
                    source = %source.id,
                    skill = %skill_path,
                    status = %resp.status(),
                    "raw SKILL.md fetch failed",
                );
                None
            }
            Err(err) => {
                warn!(
                    source = %source.id,
                    skill = %skill_path,
                    ?err,
                    "raw SKILL.md fetch network error",
                );
                None
            }
        }
    }

    async fn fetch_aggregator_json(&self, source: &CatalogSource) -> Result<Vec<CatalogEntry>> {
        let url = source
            .api_url
            .as_ref()
            .ok_or_else(|| CatalogFetchError::MissingApiUrl {
                src: source.id.clone(),
            })?;
        let resp = self
            .http
            .get(url)
            .send()
            .await
            .map_err(|e| CatalogFetchError::Network {
                src: source.id.clone(),
                message: e.to_string(),
            })?;
        let status = resp.status();
        if !status.is_success() {
            let body = resp.text().await.unwrap_or_default();
            return Err(CatalogFetchError::HttpStatus {
                src: source.id.clone(),
                status: status.as_u16(),
                body: body.chars().take(200).collect(),
            }
            .into());
        }
        let items: Vec<AggregatorItem> =
            resp.json().await.map_err(|e| CatalogFetchError::InvalidJson {
                src: source.id.clone(),
                message: e.to_string(),
            })?;

        let mut entries = Vec::with_capacity(items.len());
        for item in items {
            let owner = item.owner.unwrap_or_default().trim().to_string();
            let repo = item.repo.unwrap_or_default().trim().to_string();
            let name = item.name.unwrap_or_default().trim().to_string();
            let description = item.description.unwrap_or_default().trim().to_string();
            if owner.is_empty() || repo.is_empty() || name.is_empty() || description.is_empty() {
                continue;
            }
            let skill_path = item
                .content_path
                .map(|p| p.trim_matches('/').to_string())
                .unwrap_or_default();
            let mut metadata = serde_json::Map::new();
            for (key, val) in item.extra.iter() {
                if matches!(
                    key.as_str(),
                    "category" | "tags" | "installs" | "githubStars" | "featured" | "trending24h"
                ) && !val.is_null()
                {
                    metadata.insert(key.clone(), val.clone());
                }
            }
            entries.push(CatalogEntry {
                name,
                description,
                source_id: source.id.clone(),
                source_label: source.label.clone(),
                trust: source.trust.clone(),
                repo_owner: owner,
                repo_name: repo,
                repo_ref: source.git_ref.clone(),
                skill_path,
                license: None,
                compatibility: None,
                metadata: Value::Object(metadata),
            });
        }

        info!(source = %source.id, count = entries.len(), "aggregator source indexed");
        Ok(entries)
    }
}

/// Minimal frontmatter parser used by the GitHub fetcher — it can
/// reuse the loader's split function but only cares about the
/// frontmatter struct, not the body. Returns `None` on any parse
/// failure (the caller skips that entry).
fn parse_frontmatter_only(content: &str) -> Option<Frontmatter> {
    use crate::backend::skills::loader::split_frontmatter;
    match split_frontmatter(content) {
        Ok((fm, _)) => Some(fm),
        Err(err) => {
            warn!(?err, "skipping malformed remote SKILL.md");
            None
        }
    }
}

fn trust_rank(trust: &str) -> u8 {
    match trust {
        "official" => 0,
        "verified" => 1,
        "community" => 2,
        _ => 99,
    }
}

#[derive(Debug, Deserialize)]
struct GithubTreeResponse {
    #[serde(default)]
    tree: Vec<GithubTreeItem>,
}

#[derive(Debug, Deserialize)]
struct GithubTreeItem {
    path: String,
    #[serde(rename = "type", default)]
    kind: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AggregatorItem {
    owner: Option<String>,
    repo: Option<String>,
    name: Option<String>,
    description: Option<String>,
    content_path: Option<String>,
    #[serde(flatten)]
    extra: HashMap<String, Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trust_rank_orders_official_first() {
        assert!(trust_rank("official") < trust_rank("verified"));
        assert!(trust_rank("verified") < trust_rank("community"));
        assert!(trust_rank("community") < trust_rank("totally-unknown"));
    }

    #[test]
    fn catalog_entry_to_json_includes_derived_urls() {
        let entry = CatalogEntry {
            name: "weather".into(),
            description: "desc".into(),
            source_id: "kali".into(),
            source_label: "KALI".into(),
            trust: "verified".into(),
            repo_owner: "acme".into(),
            repo_name: "things".into(),
            repo_ref: "main".into(),
            skill_path: "skills/weather".into(),
            license: None,
            compatibility: None,
            metadata: json!({}),
        };
        let v = entry.to_json();
        assert_eq!(
            v["raw_skill_md_url"],
            "https://raw.githubusercontent.com/acme/things/main/skills/weather/SKILL.md",
        );
        assert_eq!(
            v["web_url"],
            "https://github.com/acme/things/tree/main/skills/weather",
        );
    }

    #[test]
    fn catalog_source_display_url_for_aggregator_uses_api_url() {
        let mut s = default_sources()
            .into_iter()
            .find(|s| s.id == "neuraldeep")
            .unwrap();
        assert!(s.display_url().starts_with("https://neuraldeep.ru"));
        s.api_url = None;
        // Falls back to github URL even when the api_url was the
        // intended one — defensive shape match with Python.
        assert!(s.display_url().starts_with("https://github.com/"));
    }

    #[test]
    fn default_sources_match_python_set() {
        let sources = default_sources();
        let ids: Vec<&str> = sources.iter().map(|s| s.id.as_str()).collect();
        assert_eq!(
            ids,
            vec!["anthropic", "microsoft", "voltagent", "kali", "neuraldeep"],
        );
    }
}
