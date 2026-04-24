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

/// Proxy a PATCH request with a JSON body to the Python backend.
///
/// Forwards the response status to the caller so validation errors
/// (422) from Python surface cleanly in the client. On a successful
/// status we return the parsed JSON; on a non-success status the body
/// is returned as a structured error so the caller can map it to an
/// HTTP response.
pub async fn proxy_patch_json(
    path: &str,
    body: &serde_json::Value,
) -> std::result::Result<serde_json::Value, ProxyError> {
    let base = python_backend_url();
    let url = format!("{}{}", base, path);
    let client = Client::new();
    let resp = client
        .patch(&url)
        .json(body)
        .send()
        .await
        .map_err(|e| ProxyError::Network(format!("PATCH {}: {}", url, e)))?;
    let status = resp.status();
    let payload: serde_json::Value = resp.json().await.map_err(|e| {
        ProxyError::Parse(format!("parse JSON response from PATCH {}: {}", url, e))
    })?;
    if !status.is_success() {
        return Err(ProxyError::Upstream {
            status: status.as_u16(),
            body: payload,
        });
    }
    Ok(payload)
}

/// Proxy failure modes. Kept separate from `anyhow::Error` so the
/// handler can preserve Python's HTTP status and body when forwarding
/// a non-success response to the UI.
#[derive(Debug)]
pub enum ProxyError {
    Network(String),
    Parse(String),
    Upstream {
        status: u16,
        body: serde_json::Value,
    },
}

impl std::fmt::Display for ProxyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ProxyError::Network(s) => write!(f, "network: {}", s),
            ProxyError::Parse(s) => write!(f, "parse: {}", s),
            ProxyError::Upstream { status, .. } => write!(f, "upstream status {}", status),
        }
    }
}

impl std::error::Error for ProxyError {}
