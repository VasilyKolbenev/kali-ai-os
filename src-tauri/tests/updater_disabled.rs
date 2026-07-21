//! OPUS-202: неподписанный custom-updater отключён fail-closed в shipping-сборке.
//! Продакшн-конструктор `Updater::new` НЕ ходит в сеть, НЕ качает, НЕ спавнит и
//! НЕ вызывает process::exit. Доказательство — spy-счётчик подключений (== 0),
//! а не panic-in-spawned-task (тот НЕ роняет tokio-тест).
use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use kali_desktop::backend::updater::{Phase, Updater};

// KALI_UPDATE_URL — process-global; сериализуем мутации, как updater_routes.rs.
static UPDATE_URL_ENV_LOCK: Mutex<()> = Mutex::new(());

/// Spy-листенер: считает КАЖДОЕ входящее TCP-подключение. Возвращает (url, counter).
async fn spy_listener() -> (String, Arc<AtomicUsize>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    let counter = Arc::new(AtomicUsize::new(0));
    let c2 = Arc::clone(&counter);
    tokio::spawn(async move {
        loop {
            if listener.accept().await.is_ok() {
                c2.fetch_add(1, Ordering::SeqCst);
            }
        }
    });
    (format!("http://{addr}/latest.json"), counter)
}

#[tokio::test]
async fn disabled_check_makes_no_network() {
    let (url, connects) = spy_listener().await;
    let tmp = tempfile::tempdir().unwrap();

    let u = {
        let _guard = UPDATE_URL_ENV_LOCK
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        std::env::set_var("KALI_UPDATE_URL", &url);
        let u = Updater::new(tmp.path().into(), "1.0.0");
        std::env::remove_var("KALI_UPDATE_URL");
        u
    };

    u.check().await;
    // дать возможному коннекту долететь до accept
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;

    assert_eq!(
        connects.load(Ordering::SeqCst),
        0,
        "shipping updater must not touch the network on check()"
    );
}

#[tokio::test]
async fn disabled_start_download_creates_no_update_dir() {
    let (url, connects) = spy_listener().await;
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().join("updates");

    let u = {
        let _guard = UPDATE_URL_ENV_LOCK
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        std::env::set_var("KALI_UPDATE_URL", &url);
        let u = Updater::new(root.clone(), "1.0.0");
        std::env::remove_var("KALI_UPDATE_URL");
        u
    };

    u.check().await;
    u.start_download().await;
    tokio::time::sleep(std::time::Duration::from_millis(200)).await;

    assert_eq!(connects.load(Ordering::SeqCst), 0, "no network");
    // ни одной скачанной версии-директории
    let made = std::fs::read_dir(&root).map(|d| d.count()).unwrap_or(0);
    assert_eq!(made, 0, "disabled updater must not create update dirs");
}

#[tokio::test]
async fn disabled_install_is_error_and_spawns_nothing() {
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new(tmp.path().into(), "1.0.0");
    // install на отключённом апдейтере — явная ошибка, без spawn/exit.
    let err = u.install().await.unwrap_err();
    let msg = err.to_string();
    assert!(
        msg.to_lowercase().contains("отключ") || msg.to_lowercase().contains("disabled"),
        "install() must fail-closed with a disabled reason, got: {msg}"
    );
}

#[tokio::test]
async fn disabled_status_carries_phase_and_reason() {
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new(tmp.path().into(), "1.0.0");
    let snap = u.snapshot().await;
    assert_eq!(snap.phase, Phase::Disabled);
    assert!(
        snap.reason.is_some(),
        "disabled snapshot must carry an explicit reason"
    );
    // check() не выводит из Disabled
    u.check().await;
    assert_eq!(u.snapshot().await.phase, Phase::Disabled);
}
