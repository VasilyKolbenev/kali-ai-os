use anyhow::{Context, Result};
use reqwest::Client;

pub fn python_backend_url() -> String {
    std::env::var("KALI_PYTHON_BACKEND_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:3005".to_string())
}

/// Proxy a GET request to the Python backend and return the response body.
/// Streaming is not used here — voice/status payload is tiny. For large
/// responses (TTS audio), revisit when those endpoints migrate.
pub async fn proxy_get_json(path: &str) -> Result<serde_json::Value> {
    let base = python_backend_url();
    let url = format!("{}{}", base, path);
    let client = Client::new();
    let resp = client
        .get(&url)
        .send()
        .await
        .with_context(|| format!("GET {}", url))?;
    let status = resp.status();
    if !status.is_success() {
        anyhow::bail!("Python backend returned {} for {}", status, url);
    }
    resp.json::<serde_json::Value>()
        .await
        .with_context(|| format!("parse JSON from {}", url))
}
