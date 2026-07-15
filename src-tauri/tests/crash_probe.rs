//! Проб Python-liveness. КЛЮЧЕВОЕ: зависший Python не должен вешать хендлер —
//! у проба СВОЙ таймаут (proxy::proxy_get_json таймаута НЕ имеет).
use std::net::SocketAddr;
use std::time::{Duration, Instant};

use axum::{routing::get, Router};
use kali_desktop::backend::crash::probe_backend_alive_with;

async fn spawn_health(alive: bool, hang: bool) -> String {
    let app = Router::new().route(
        "/health",
        get(move || async move {
            if hang {
                // «завис»: принял соединение, но не отвечает
                tokio::time::sleep(Duration::from_secs(30)).await;
            }
            if alive {
                (axum::http::StatusCode::OK, "ok")
            } else {
                (axum::http::StatusCode::INTERNAL_SERVER_ERROR, "down")
            }
        }),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr: SocketAddr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
    format!("http://{addr}")
}

#[tokio::test]
async fn alive_backend_reports_true() {
    let base = spawn_health(true, false).await;
    assert!(probe_backend_alive_with(&base, Duration::from_secs(2)).await);
}

#[tokio::test]
async fn non_success_status_reports_false() {
    let base = spawn_health(false, false).await;
    assert!(!probe_backend_alive_with(&base, Duration::from_secs(2)).await);
}

/// ОТСТУПЛЕНИЕ ОТ ПЛАНА (эмпирически обосновано, см. отчёт Task 3).
///
/// План давал пробу таймаут 2с и требовал `elapsed() < 2с`. На Windows-машине
/// Vasily закрытый loopback-порт отдаёт RST не мгновенно, а через ~2.03-2.06с
/// (замерено голым `TcpStream::connect_timeout` с бюджетом 5с — без reqwest и
/// tokio: `ConnectionRefused` в 2.03-2.06с на портах 1, 9 и на свежеотпущенном
/// высоком порту). То есть таймаут (2.00с) всегда выигрывал гонку у отказа
/// (~2.05с) → тест не мог пройти НИКОГДА, хотя код верен.
///
/// Сохраняем СМЫСЛ теста («мёртвый порт не ждёт весь таймаут»), разведя две
/// величины: бюджет 30с, порог 10с. Прежний баг всё ещё ловится — если проб
/// повиснет (SYN в чёрную дыру, таймаут снят), elapsed станет 30с → красный.
#[tokio::test]
async fn dead_port_reports_false_without_burning_the_whole_timeout() {
    // на этот порт никто не слушает → connection refused
    let started = Instant::now();
    let alive = probe_backend_alive_with("http://127.0.0.1:1", Duration::from_secs(30)).await;
    assert!(!alive);
    assert!(
        started.elapsed() < Duration::from_secs(10),
        "мёртвый порт должен падать по отказу, а не выжигать весь таймаут"
    );
}

#[tokio::test]
async fn hung_backend_times_out_and_reports_false() {
    let base = spawn_health(true, true).await;
    let started = Instant::now();
    let alive = probe_backend_alive_with(&base, Duration::from_millis(300)).await;
    assert!(!alive, "зависший backend должен считаться мёртвым");
    assert!(started.elapsed() < Duration::from_secs(5), "проб повис — таймаут не сработал");
}
