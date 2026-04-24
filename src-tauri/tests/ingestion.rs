//! End-to-end: Python-style HTTP POST to /_internal/events fans out to
//! every connected /ws subscriber. Also covers optional-field defaults and
//! malformed body rejection.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use futures_util::StreamExt;
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use kali_desktop::backend::event_bus::EventBus;
use kali_desktop::backend::http::router_with_bus;

async fn spawn_server() -> (SocketAddr, Arc<EventBus>) {
    let bus = Arc::new(EventBus::new());
    let app = router_with_bus(bus.clone());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(
            listener,
            app.into_make_service_with_connect_info::<SocketAddr>(),
        )
        .await
        .unwrap();
    });
    (addr, bus)
}

#[tokio::test]
async fn ingested_event_reaches_ws_client() {
    let (addr, _bus) = spawn_server().await;
    let ws_url = format!("ws://{}/ws", addr);
    let (mut client, _) = connect_async(&ws_url).await.unwrap();
    tokio::time::sleep(Duration::from_millis(100)).await;

    let body = json!({
        "topic": "voice.pipeline",
        "source": "python",
        "payload": { "active": true },
        "timestamp": "2026-05-09T12:00:00Z",
        "correlation_id": "cid-1"
    });
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 202);
    let body_resp: Value = resp.json().await.unwrap();
    assert_eq!(body_resp["delivered"], 1);

    let frame = tokio::time::timeout(Duration::from_secs(2), client.next())
        .await
        .expect("client recv timed out")
        .expect("client stream closed")
        .expect("client frame error");
    let Message::Text(raw) = frame else {
        panic!("expected text frame, got {:?}", frame);
    };
    let parsed: Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(parsed["type"], "voice.pipeline");
    assert_eq!(parsed["data"]["active"], true);
}

#[tokio::test]
async fn ingestion_accepts_event_without_optional_fields() {
    // Python populates `timestamp` and `correlation_id` server-side, but
    // defense in depth: missing optional fields must default cleanly.
    let (addr, _bus) = spawn_server().await;
    let body = json!({
        "topic": "system.startup",
        "source": "python",
        "payload": {}
    });
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert_eq!(resp.status(), 202);
}

#[tokio::test]
async fn ingestion_rejects_malformed_body_with_4xx() {
    let (addr, _bus) = spawn_server().await;
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .body("not-json")
        .header("content-type", "application/json")
        .send()
        .await
        .unwrap();
    assert!(resp.status().is_client_error(), "got {}", resp.status());
}

#[tokio::test]
async fn ingestion_rejects_missing_required_fields_with_4xx() {
    let (addr, _bus) = spawn_server().await;
    // No `topic` → Serde deserialise fails with 4xx.
    let body = json!({
        "source": "python",
        "payload": {}
    });
    let resp = reqwest::Client::new()
        .post(format!("http://{}/_internal/events", addr))
        .json(&body)
        .send()
        .await
        .unwrap();
    assert!(resp.status().is_client_error(), "got {}", resp.status());
}
