//! Полный flow: check → download → verify → Ready; ошибки хэша.
use axum::{routing::get, Router};
use kali_desktop::backend::updater::{Phase, Updater};
use sha2::{Digest, Sha256};
use std::net::SocketAddr;

const A1: &[u8] = b"first-asset-bytes";
const A2: &[u8] = b"second-asset-bytes!!";

fn manifest_json(base: &str, corrupt_sha: bool) -> String {
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

async fn spawn_release_srv(corrupt_sha: bool) -> String {
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

// NB: мок сервит http://127.0.0.1-URL — parse_manifest разрешает loopback-http
// (контракт для локального E2E-гейта спеки), поэтому спец-флагов не нужно.

#[tokio::test]
async fn check_download_verify_reaches_ready() {
    let base = spawn_release_srv(false).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0-rc1", &format!("{base}/latest.json"));

    let snap = u.check().await;
    assert_eq!(snap.phase, Phase::Available);
    assert_eq!(snap.available.as_ref().unwrap().version, "9.9.9");

    u.start_download().await;
    u.wait_terminal().await; // тест-хелпер: ждёт Ready|Error
    let snap = u.snapshot().await;
    assert_eq!(snap.phase, Phase::Ready, "err={:?}", snap.error);
    assert_eq!(snap.downloaded, snap.total);
    // save-by-name
    assert!(tmp.path().join("9.9.9").join("KALI-Premium-Setup-9.9.9.exe").exists());
    assert!(tmp.path().join("9.9.9").join("KALI-Premium-Setup-9.9.9-1.bin").exists());
}

#[tokio::test]
async fn same_or_older_version_stays_idle() {
    let base = spawn_release_srv(false).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "9.9.9", &format!("{base}/latest.json"));
    let snap = u.check().await;
    assert_eq!(snap.phase, Phase::Idle);
}

#[tokio::test]
async fn unreachable_manifest_is_silent_idle() {
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", "http://127.0.0.1:1/latest.json");
    let snap = u.check().await;
    assert_eq!(snap.phase, Phase::Idle);
    assert!(snap.error.is_none()); // тихий пропуск, не ошибка
}

#[tokio::test]
async fn sha_mismatch_ends_in_error_and_deletes_file() {
    let base = spawn_release_srv(true).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", &format!("{base}/latest.json"));
    u.check().await;
    u.start_download().await;
    u.wait_terminal().await;
    let snap = u.snapshot().await;
    assert_eq!(snap.phase, Phase::Error);
    assert!(snap.error.is_some());
    // битый файл удалён — retry скачает заново
    assert!(!tmp.path().join("9.9.9").join("KALI-Premium-Setup-9.9.9-1.bin").exists());
}

#[tokio::test]
async fn download_without_available_is_noop() {
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", "http://127.0.0.1:1/x");
    u.start_download().await;
    assert_eq!(u.snapshot().await.phase, Phase::Idle);
}
