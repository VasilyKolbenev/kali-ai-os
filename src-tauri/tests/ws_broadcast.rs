//! WS contract: connected clients receive every event published on the
//! shared bus, and `ui.command` frames from a client are re-published on the
//! bus with `source="websocket"`. Serves as the Phase 2 Chunk 1 smoke test.

use std::sync::Arc;
use std::time::Duration;

use axum::Router;
use futures_util::{SinkExt, StreamExt};
use serde_json::{json, Value};
use tokio::net::TcpListener;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use kali_desktop::backend::event_bus::EventBus;
use kali_desktop::backend::http::router_with_bus;
use kali_desktop::backend::models::Event;

async fn spawn_server() -> (std::net::SocketAddr, Arc<EventBus>) {
    let bus = Arc::new(EventBus::new());
    let app: Router = router_with_bus(bus.clone());
    let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    (addr, bus)
}

fn make_event(topic: &str, payload: Value) -> Event {
    Event {
        topic: topic.to_string(),
        source: "kernel".to_string(),
        payload,
        timestamp: chrono::Utc::now(),
        correlation_id: "test".to_string(),
    }
}

#[tokio::test]
async fn publish_fans_out_to_all_connected_clients() {
    let (addr, bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);

    let (mut client_a, _) = connect_async(&url).await.expect("client A connect");
    let (mut client_b, _) = connect_async(&url).await.expect("client B connect");

    // Give the server a beat to register both subscribers before we publish.
    tokio::time::sleep(Duration::from_millis(100)).await;
    assert_eq!(bus.subscriber_count(), 2);

    bus.publish(make_event("voice.state", json!({ "state": "listening" })));

    let a_msg = tokio::time::timeout(Duration::from_secs(2), client_a.next())
        .await
        .expect("A timed out")
        .expect("A stream closed")
        .expect("A frame error");
    let b_msg = tokio::time::timeout(Duration::from_secs(2), client_b.next())
        .await
        .expect("B timed out")
        .expect("B stream closed")
        .expect("B frame error");

    for msg in [a_msg, b_msg] {
        let Message::Text(raw) = msg else {
            panic!("expected text frame, got {:?}", msg);
        };
        let parsed: Value = serde_json::from_str(&raw).unwrap();
        assert_eq!(parsed["type"], "voice.state");
        assert_eq!(parsed["data"]["state"], "listening");
    }
}

#[tokio::test]
async fn ui_command_from_client_is_published_back_on_bus() {
    let (addr, bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);

    let mut rx = bus.subscribe();
    let (mut client, _) = connect_async(&url).await.expect("connect");
    tokio::time::sleep(Duration::from_millis(100)).await;

    let frame = json!({ "type": "ui.command", "data": { "name": "open.settings" } });
    client
        .send(Message::Text(frame.to_string()))
        .await
        .expect("send");

    let event = tokio::time::timeout(Duration::from_secs(2), rx.recv())
        .await
        .expect("timeout")
        .expect("recv");
    assert_eq!(event.topic, "ui.command");
    assert_eq!(event.source, "websocket");
    assert_eq!(event.payload["name"], "open.settings");
}

#[tokio::test]
async fn malformed_frame_does_not_disconnect_client() {
    let (addr, bus) = spawn_server().await;
    let url = format!("ws://{}/ws", addr);
    let (mut client, _) = connect_async(&url).await.expect("connect");
    tokio::time::sleep(Duration::from_millis(100)).await;

    // Garbage frame: must be ignored without closing the socket.
    client
        .send(Message::Text("not-json".into()))
        .await
        .expect("send garbage");

    // A subsequent real event must still reach this client.
    bus.publish(make_event("voice.state", json!({ "state": "idle" })));

    let frame = tokio::time::timeout(Duration::from_secs(2), client.next())
        .await
        .expect("still-connected timeout")
        .expect("stream closed after garbage")
        .expect("frame error");
    let Message::Text(raw) = frame else {
        panic!("expected text frame, got {:?}", frame);
    };
    let parsed: Value = serde_json::from_str(&raw).unwrap();
    assert_eq!(parsed["type"], "voice.state");
}
