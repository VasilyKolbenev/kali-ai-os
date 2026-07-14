//! Общий release-мок для интеграционных тестов апдейтера: сервит и манифест,
//! и два ассета на loopback-адресе (parse_manifest разрешает http://127.0.0.1).
//! Каждый тест-бинарь компилирует этот модуль независимо и использует не всё —
//! отсюда #[allow(dead_code)].
#![allow(dead_code)]

use axum::{routing::get, Router};
use sha2::{Digest, Sha256};
use std::net::SocketAddr;

pub const A1: &[u8] = b"first-asset-bytes";
pub const A2: &[u8] = b"second-asset-bytes!!";

pub fn manifest_json(base: &str, corrupt_sha: bool) -> String {
    let sha1 = hex::encode(Sha256::digest(A1));
    let sha2_ = if corrupt_sha {
        "0".repeat(64)
    } else {
        hex::encode(Sha256::digest(A2))
    };
    format!(
        r#"{{"version":"9.9.9","notes":"n","assets":[
            {{"name":"KALI-Premium-Setup-9.9.9.exe","url":"{base}/KALI-Premium-Setup-9.9.9.exe","sha256":"{sha1}","size":{}}},
            {{"name":"KALI-Premium-Setup-9.9.9-1.bin","url":"{base}/KALI-Premium-Setup-9.9.9-1.bin","sha256":"{sha2_}","size":{}}}
        ]}}"#,
        A1.len(),
        A2.len()
    )
}

pub async fn spawn_release_srv(corrupt_sha: bool) -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    let base = format!("http://{addr}");
    let b2 = base.clone();
    let app = Router::new()
        .route(
            "/latest.json",
            get(move || {
                let m = manifest_json(&b2, corrupt_sha);
                async move { m }
            }),
        )
        .route("/KALI-Premium-Setup-9.9.9.exe", get(|| async { A1.to_vec() }))
        .route("/KALI-Premium-Setup-9.9.9-1.bin", get(|| async { A2.to_vec() }));
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    base
}
