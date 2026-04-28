//! Phase 4 Chunk 2 — remote catalog integration test.
//!
//! Spins up a local axum server impersonating GitHub's REST API +
//! raw.githubusercontent.com layer, points the `CatalogClient` at it
//! via the env-var override knobs (`KALI_GITHUB_API_URL` and
//! `KALI_GITHUB_RAW_URL`), and exercises the full fetch → parse →
//! cache round-trip.
//!
//! Single combined `#[tokio::test]` by design — the GitHub URL env
//! vars are process-wide; parallel tests would race on them. Same
//! pattern as `voice_routes_proxy.rs`.

use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

use axum::{
    extract::{Path, State},
    routing::get,
    Json, Router,
};
use serde_json::{json, Value};
use tokio::net::TcpListener;

use kali_desktop::backend::skills::catalog::{
    CatalogClient, CatalogClientOpts, CatalogSource,
};

#[derive(Clone, Default)]
struct MockState {
    /// How many times the API server was hit. Used to verify caching.
    api_hits: Arc<AtomicUsize>,
    /// How many times the raw server was hit. Same idea.
    raw_hits: Arc<AtomicUsize>,
}

async fn mock_tree(
    State(state): State<MockState>,
    Path((owner, repo)): Path<(String, String)>,
) -> Json<Value> {
    state.api_hits.fetch_add(1, Ordering::Relaxed);
    // Two skills under skills/, plus a noise SKILL.md outside the
    // configured prefix to verify path filtering.
    Json(json!({
        "tree": [
            { "type": "blob", "path": "skills/alpha/SKILL.md" },
            { "type": "blob", "path": "skills/beta/SKILL.md" },
            { "type": "blob", "path": "noise/SKILL.md" },
            { "type": "tree", "path": "skills" },
        ],
        "owner": owner,
        "repo": repo,
    }))
}

async fn mock_raw(
    State(state): State<MockState>,
    Path((owner, repo, git_ref, skill_dir, _file)): Path<(
        String,
        String,
        String,
        String,
        String,
    )>,
) -> String {
    state.raw_hits.fetch_add(1, Ordering::Relaxed);
    let _ = (owner, repo, git_ref);
    let dir_name = skill_dir.split('/').last().unwrap_or("?").to_string();
    format!(
        r#"---
name: {dir_name}
description: Mocked SKILL.md for {dir_name}.
license: MIT
metadata:
  category: test
---

# {dir_name}

Body for {dir_name}.
"#
    )
}

#[tokio::test]
async fn catalog_fetches_parses_and_caches_a_github_source() {
    let state = MockState::default();

    // ---- Mock API server ----
    let api_state = state.clone();
    let api_router: Router = Router::new()
        .route(
            "/repos/:owner/:repo/git/trees/:ref",
            get(mock_tree),
        )
        .with_state(api_state);
    let api_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let api_addr = api_listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(api_listener, api_router).await.unwrap();
    });

    // ---- Mock raw.githubusercontent.com server ----
    let raw_state = state.clone();
    let raw_router: Router = Router::new()
        .route(
            "/:owner/:repo/:ref/skills/:skill/:file",
            get(mock_raw),
        )
        .with_state(raw_state);
    let raw_listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let raw_addr = raw_listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(raw_listener, raw_router).await.unwrap();
    });

    // ---- CatalogClient configured against the mocks ----
    let cache_dir = tempfile::tempdir().unwrap();
    let opts = CatalogClientOpts {
        sources: vec![CatalogSource {
            id: "test".into(),
            label: "Test Source".into(),
            owner: "acme".into(),
            repo: "things".into(),
            git_ref: "main".into(),
            skills_path: "skills".into(),
            trust: "verified".into(),
            source_type: "github".into(),
            api_url: None,
        }],
        cache_dir: cache_dir.path().to_path_buf() as PathBuf,
        api_base: format!("http://{}", api_addr),
        raw_base: format!("http://{}", raw_addr),
        http_timeout: Duration::from_secs(5),
        cache_ttl_seconds: 3600,
    };
    let client = CatalogClient::new(opts).expect("build catalog client");

    // ---- 1. First refresh hits HTTP, indexes 2 entries ----
    let entries = client
        .refresh_source("test", false)
        .await
        .expect("refresh ok");
    assert_eq!(entries.len(), 2, "expected 2 SKILL.md inside skills/ prefix");
    assert_eq!(state.api_hits.load(Ordering::Relaxed), 1);
    assert_eq!(state.raw_hits.load(Ordering::Relaxed), 2);

    let names: Vec<&str> = entries.iter().map(|e| e.name.as_str()).collect();
    assert!(names.contains(&"alpha"));
    assert!(names.contains(&"beta"));

    // Skill paths should drop the trailing /SKILL.md.
    let alpha = entries.iter().find(|e| e.name == "alpha").unwrap();
    assert_eq!(alpha.skill_path, "skills/alpha");
    assert_eq!(alpha.source_id, "test");
    assert_eq!(alpha.trust, "verified");
    assert_eq!(alpha.repo_owner, "acme");
    assert_eq!(alpha.license.as_deref(), Some("MIT"));

    // Derived URLs use the public GitHub origin (Python parity), even
    // though we fetched from a local mock — the URLs are user-facing
    // links, not the fetch path.
    let json = alpha.to_json();
    assert_eq!(
        json["raw_skill_md_url"],
        "https://raw.githubusercontent.com/acme/things/main/skills/alpha/SKILL.md",
    );
    assert_eq!(
        json["web_url"],
        "https://github.com/acme/things/tree/main/skills/alpha",
    );

    // ---- 2. Second refresh (force=false) is served from cache; no extra hits ----
    let cached = client
        .refresh_source("test", false)
        .await
        .expect("cache hit");
    assert_eq!(cached.len(), 2);
    assert_eq!(
        state.api_hits.load(Ordering::Relaxed),
        1,
        "second refresh must not re-hit GitHub when cache is fresh",
    );
    assert_eq!(state.raw_hits.load(Ordering::Relaxed), 2);

    // ---- 3. Forced refresh re-hits the network ----
    let forced = client
        .refresh_source("test", true)
        .await
        .expect("force refresh ok");
    assert_eq!(forced.len(), 2);
    assert_eq!(
        state.api_hits.load(Ordering::Relaxed),
        2,
        "forced refresh must re-hit the API",
    );
    assert_eq!(state.raw_hits.load(Ordering::Relaxed), 4);

    // ---- 4. List + search wire correctly ----
    let all = client.list_all().await;
    assert_eq!(all.len(), 2);
    let hits = client.search("alpha").await;
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].name, "alpha");
    let none = client.search("zzz-no-match").await;
    assert!(none.is_empty());

    // ---- 5. Sources summary contains expected fields ----
    let summary = client.sources_summary();
    assert_eq!(summary["sources"][0]["id"], "test");
    assert_eq!(summary["sources"][0]["trust"], "verified");
    assert!(summary["sources"][0]["url"]
        .as_str()
        .unwrap()
        .starts_with("https://github.com/acme/things"));
}
