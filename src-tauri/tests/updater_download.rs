//! Скачивание с Range-резюмом + SHA-256 — против локального axum-мока.
use axum::{
    extract::State,
    http::{header, HeaderMap, StatusCode},
    routing::get,
    Router,
};
use kali_desktop::backend::updater::{download_asset, sha256_file, Asset};
use sha2::{Digest, Sha256};
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

const BODY: &[u8] = b"0123456789abcdef0123456789abcdef"; // 32 байта

fn sha_hex(b: &[u8]) -> String {
    hex::encode(Sha256::digest(b))
}

#[derive(Clone)]
struct Srv {
    hits: Arc<AtomicUsize>,
    honor_range: bool,
}

async fn serve_asset(State(s): State<Srv>, headers: HeaderMap) -> (StatusCode, HeaderMap, Vec<u8>) {
    s.hits.fetch_add(1, Ordering::SeqCst);
    let mut out = HeaderMap::new();
    if s.honor_range {
        if let Some(r) = headers.get(header::RANGE) {
            let from: usize = r
                .to_str()
                .unwrap()
                .trim_start_matches("bytes=")
                .trim_end_matches('-')
                .parse()
                .unwrap();
            out.insert(
                header::CONTENT_RANGE,
                format!("bytes {}-{}/{}", from, BODY.len() - 1, BODY.len())
                    .parse()
                    .unwrap(),
            );
            return (StatusCode::PARTIAL_CONTENT, out, BODY[from..].to_vec());
        }
    }
    (StatusCode::OK, out, BODY.to_vec())
}

async fn spawn_srv(honor_range: bool) -> (String, Arc<AtomicUsize>) {
    let hits = Arc::new(AtomicUsize::new(0));
    let app = Router::new()
        .route("/a.bin", get(serve_asset))
        .with_state(Srv { hits: hits.clone(), honor_range });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    (format!("http://{addr}/a.bin"), hits)
}

fn asset(url: &str) -> Asset {
    Asset {
        name: "a.bin".into(),
        url: url.into(),
        sha256: sha_hex(BODY),
        size: BODY.len() as u64,
    }
}

#[tokio::test]
async fn downloads_fresh_file_and_reports_progress() {
    let (url, _) = spawn_srv(true).await;
    let tmp = tempfile::tempdir().unwrap();
    let got = Arc::new(AtomicUsize::new(0));
    let g2 = got.clone();
    download_asset(
        &reqwest::Client::new(),
        &asset(&url),
        tmp.path(),
        &move |d| {
            g2.fetch_add(d as usize, Ordering::SeqCst);
        },
    )
    .await
    .unwrap();
    assert_eq!(std::fs::read(tmp.path().join("a.bin")).unwrap(), BODY);
    assert_eq!(got.load(Ordering::SeqCst), BODY.len());
}

#[tokio::test]
async fn resumes_partial_file_with_range() {
    let (url, _) = spawn_srv(true).await;
    let tmp = tempfile::tempdir().unwrap();
    std::fs::write(tmp.path().join("a.bin"), &BODY[..10]).unwrap(); // обрыв на 10 байтах
    let got = Arc::new(AtomicUsize::new(0));
    let g2 = got.clone();
    download_asset(&reqwest::Client::new(), &asset(&url), tmp.path(), &move |d| {
        g2.fetch_add(d as usize, Ordering::SeqCst);
    })
    .await
    .unwrap();
    assert_eq!(std::fs::read(tmp.path().join("a.bin")).unwrap(), BODY);
    // докачаны только недостающие байты
    assert_eq!(got.load(Ordering::SeqCst), BODY.len() - 10);
}

#[tokio::test]
async fn server_ignoring_range_restarts_from_scratch() {
    let (url, _) = spawn_srv(false).await; // мок игнорирует Range → 200 + полное тело
    let tmp = tempfile::tempdir().unwrap();
    std::fs::write(tmp.path().join("a.bin"), &BODY[..10]).unwrap();
    download_asset(&reqwest::Client::new(), &asset(&url), tmp.path(), &|_| {})
        .await
        .unwrap();
    assert_eq!(std::fs::read(tmp.path().join("a.bin")).unwrap(), BODY);
}

#[tokio::test]
async fn oversized_local_file_is_discarded_and_redownloaded() {
    let (url, _) = spawn_srv(true).await;
    let tmp = tempfile::tempdir().unwrap();
    std::fs::write(tmp.path().join("a.bin"), [0u8; 100]).unwrap(); // len > size
    download_asset(&reqwest::Client::new(), &asset(&url), tmp.path(), &|_| {})
        .await
        .unwrap();
    assert_eq!(std::fs::read(tmp.path().join("a.bin")).unwrap(), BODY);
}

#[tokio::test]
async fn complete_file_is_not_refetched() {
    let (url, hits) = spawn_srv(true).await;
    let tmp = tempfile::tempdir().unwrap();
    std::fs::write(tmp.path().join("a.bin"), BODY).unwrap();
    download_asset(&reqwest::Client::new(), &asset(&url), tmp.path(), &|_| {})
        .await
        .unwrap();
    assert_eq!(hits.load(Ordering::SeqCst), 0); // ни одного запроса
}

#[tokio::test]
async fn sha256_file_matches() {
    let tmp = tempfile::tempdir().unwrap();
    let p = tmp.path().join("x");
    std::fs::write(&p, BODY).unwrap();
    assert_eq!(sha256_file(&p).await.unwrap(), sha_hex(BODY));
}
