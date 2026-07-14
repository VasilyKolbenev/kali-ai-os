# Auto-update (Windows) — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Полуавто-обновление KALI desktop: чек манифеста в репо → резюмируемое скачивание 4 InnoSetup-файлов с GitHub Releases → SHA-256 → тихая установка → перезапуск.

**Architecture:** Ядро — `src-tauri/src/backend/updater.rs` (state-machine + сеть/файлы), транспорт — HTTP-роуты существующего axum control-plane :3006 (UI не использует tauri-команды). UI — Zustand-стор с поллингом `/updater/status` + баннер. Публикация — `scripts/publish_release.py` (валидация версий → draft-релиз → ассеты → undraft → коммит `releases/latest.json` = атомарный флип).

**Tech Stack:** Rust (reqwest stream, sha2, semver, fs4, axum, tokio), React 19 + Zustand + vitest, InnoSetup, Python + gh CLI.

**Spec:** `docs/superpowers/specs/2026-07-14-auto-update-design.md` — прочитать ПЕРЕД началом. Гейты: `cd src-tauri && cargo test --test <file>` · `cd ui && pnpm exec vitest run` · полный прогон перед пушем.

> **ГОТЧА (Windows Installer Detection):** тест-бинарники `updater_*` содержат подстроку «update»/«install» → UAC-эвристика требует elevation и `cargo test` падает с `os error 740` ДО запуска тестов на обычном (не-админ) аккаунте. Обход — запускать под `RunAsInvoker` shim (env наследуется в дочерний тест-бинарь):
> ```powershell
> $env:__COMPAT_LAYER='RunAsInvoker'; cargo test --test updater_core
> ```
> Это же зашито в CI-шаг (Task 9). Имена тестов НЕ переименовываем (самодокументируемы); shim — легитимный штатный механизм Windows.

---

## Chunk 1: Rust core

### Task 1: Манифест, semver, аргументы инсталятора, cleanup (чистые функции)

**Files:**
- Modify: `src-tauri/Cargo.toml` (deps)
- Create: `src-tauri/src/backend/updater.rs`
- Modify: `src-tauri/src/backend/mod.rs` (объявить модуль — посмотреть, как объявлены соседи, напр. `pub mod updater;`)
- Test: `src-tauri/tests/updater_core.rs`

- [ ] **Step 1: Добавить зависимости в Cargo.toml**

В `[dependencies]` (reqwest уже есть — добавить feature `stream`):

```toml
reqwest = { version = "0.12", features = ["json", "stream"] }
# auto-update: SHA-256 верификация ассетов
sha2 = "0.10"
# auto-update: сравнение версий манифеста (rc-pre-release семантика из коробки)
semver = "1"
# auto-update: свободное место на диске перед скачиванием 4.2 GB
fs4 = "0.13"
hex = "0.4"
```

- [ ] **Step 2: Написать падающие тесты**

`src-tauri/tests/updater_core.rs`:

```rust
//! Unit-тесты чистых функций апдейтера: манифест, semver, args, cleanup.
use kali_desktop::backend::updater::{
    build_install_args, cleanup_updates_dir, is_newer, parse_manifest,
};

const GOOD: &str = r#"{
  "version": "1.0.1", "pub_date": "2026-07-20T12:00:00Z", "notes": "notes",
  "assets": [
    {"name": "KALI-Premium-Setup-1.0.1.exe", "url": "https://github.com/x/y/releases/download/v1.0.1/KALI-Premium-Setup-1.0.1.exe", "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "size": 10},
    {"name": "KALI-Premium-Setup-1.0.1-1.bin", "url": "https://github.com/x/y/releases/download/v1.0.1/KALI-Premium-Setup-1.0.1-1.bin", "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "size": 20}
  ]
}"#;

#[test]
fn parses_good_manifest() {
    let m = parse_manifest(GOOD).unwrap();
    assert_eq!(m.version, "1.0.1");
    assert_eq!(m.assets.len(), 2);
    assert_eq!(m.total_size(), 30);
}

#[test]
fn rejects_bad_manifests() {
    assert!(parse_manifest("not json").is_err());
    assert!(parse_manifest(r#"{"version":"1.0.1","assets":[]}"#).is_err());
    // path traversal в имени ассета
    let evil = GOOD.replace("KALI-Premium-Setup-1.0.1.exe", "..\\evil.exe");
    assert!(parse_manifest(&evil).is_err());
    let evil2 = GOOD.replace("KALI-Premium-Setup-1.0.1.exe", "a/b.exe");
    assert!(parse_manifest(&evil2).is_err());
    // http:// URL
    let http = GOOD.replace("https://", "http://");
    assert!(parse_manifest(&http).is_err());
    // битый sha256
    let bad_sha = GOOD.replace("aaaaaaaa", "zzzzzzzz");
    assert!(parse_manifest(&bad_sha).is_err());
    // невалидная версия
    let bad_ver = GOOD.replace("\"version\": \"1.0.1\"", "\"version\": \"latest\"");
    assert!(parse_manifest(&bad_ver).is_err());
}

#[test]
fn semver_ordering_with_prerelease() {
    assert!(is_newer("1.0.0-rc1", "1.0.0"));   // rc < release
    assert!(is_newer("1.0.0", "1.0.1"));
    assert!(is_newer("1.0.0-rc1", "1.0.0-rc2"));
    assert!(!is_newer("1.0.1", "1.0.0"));
    assert!(!is_newer("1.0.0", "1.0.0"));
    assert!(!is_newer("1.0.0", "garbage"));     // непарсящееся = не новее
}

#[test]
fn install_args_exact() {
    let args = build_install_args(
        std::path::Path::new(r"C:\u\KALI-Premium-Setup-1.0.1.exe"),
        std::path::Path::new(r"C:\Users\U\AppData\Local\Programs\KALI"),
        std::path::Path::new(r"C:\u\updates\1.0.1\install.log"),
    );
    assert_eq!(
        args,
        vec![
            "/VERYSILENT".to_string(),
            "/SUPPRESSMSGBOXES".to_string(),
            "/NORESTART".to_string(),
            r"/LOG=C:\u\updates\1.0.1\install.log".to_string(),
            r"/DIR=C:\Users\U\AppData\Local\Programs\KALI".to_string(),
        ]
    );
}

#[test]
fn cleanup_keeps_only_strictly_newer_semver_dirs() {
    let tmp = tempfile::tempdir().unwrap();
    for d in ["1.0.0", "1.0.1", "1.0.0-rc1", "junk", "2.0.0"] {
        std::fs::create_dir(tmp.path().join(d)).unwrap();
        std::fs::write(tmp.path().join(d).join("f.bin"), b"x").unwrap();
    }
    cleanup_updates_dir(tmp.path(), "1.0.0");
    let left: Vec<String> = std::fs::read_dir(tmp.path())
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    // строго новее 1.0.0: только 1.0.1 и 2.0.0; junk и rc1 (старее) удалены
    assert_eq!(left.len(), 2, "left: {left:?}");
    assert!(left.contains(&"1.0.1".to_string()));
    assert!(left.contains(&"2.0.0".to_string()));
}
```

- [ ] **Step 3: Запустить — убедиться, что падают**

Run: `cd src-tauri; cargo test --test updater_core` → FAIL (модуль не существует).

- [ ] **Step 4: Минимальная реализация**

`src-tauri/src/backend/updater.rs` (начало файла; state-machine добавится в Task 3):

```rust
//! Auto-update: манифест в репо → резюмируемое скачивание с GitHub Releases →
//! SHA-256 → тихий InnoSetup. Спека: docs/superpowers/specs/2026-07-14-auto-update-design.md
//! Транспорт — HTTP-роуты control-plane (:3006), см. http.rs.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Манифест живёт в репо (НЕ в release-ассетах): `releases/latest/` GitHub
/// не отдаёт pre-release, а мы шипим rc-версии. Коммит манифеста = флип публикации.
pub const DEFAULT_MANIFEST_URL: &str =
    "https://raw.githubusercontent.com/VasilyKolbenev/kali-ai-os/main/releases/latest.json";

pub fn manifest_url() -> String {
    std::env::var("KALI_UPDATE_URL").unwrap_or_else(|_| DEFAULT_MANIFEST_URL.to_string())
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Asset {
    pub name: String,
    pub url: String,
    pub sha256: String,
    pub size: u64,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct Manifest {
    pub version: String,
    #[serde(default)]
    pub pub_date: String,
    #[serde(default)]
    pub notes: String,
    pub assets: Vec<Asset>,
}

impl Manifest {
    pub fn total_size(&self) -> u64 {
        self.assets.iter().map(|a| a.size).sum()
    }
}

pub fn parse_manifest(raw: &str) -> Result<Manifest> {
    let m: Manifest = serde_json::from_str(raw).context("manifest: invalid JSON")?;
    semver::Version::parse(&m.version).context("manifest: version is not semver")?;
    if m.assets.is_empty() {
        bail!("manifest: assets is empty");
    }
    for a in &m.assets {
        // DiskSpanning требует оригинальные имена; имя обязано быть голым файлом —
        // никакого траверсала в updates-директорию.
        if a.name.is_empty() || a.name.contains(['/', '\\']) || a.name.contains("..") {
            bail!("manifest: unsafe asset name {:?}", a.name);
        }
        // https обязателен; loopback-http разрешён для локального E2E-гейта спеки
        // (KALI_UPDATE_URL → фейковый релиз на 127.0.0.1) и интеграционных тестов.
        // После хоста обязателен ':' или '/' — иначе префикс обходится доменом
        // вида 127.0.0.1.evil.example.
        let loopback_http = ["http://127.0.0.1", "http://localhost"].iter().any(|p| {
            a.url
                .strip_prefix(p)
                .map(|rest| rest.starts_with([':', '/']))
                .unwrap_or(false)
        });
        if !a.url.starts_with("https://") && !loopback_http {
            bail!("manifest: non-https url for {}", a.name);
        }
        if a.sha256.len() != 64 || !a.sha256.chars().all(|c| c.is_ascii_hexdigit()) {
            bail!("manifest: bad sha256 for {}", a.name);
        }
        if a.size == 0 {
            bail!("manifest: zero size for {}", a.name);
        }
    }
    Ok(m)
}

/// Кандидат новее текущей? Непарсящееся никогда не новее (тихий отказ).
pub fn is_newer(current: &str, candidate: &str) -> bool {
    match (
        semver::Version::parse(current),
        semver::Version::parse(candidate),
    ) {
        (Ok(cur), Ok(cand)) => cand > cur,
        _ => false,
    }
}

/// Точный порядок и формат аргументов — контракт со спекой и E2E-тестом.
pub fn build_install_args(_setup_exe: &Path, install_dir: &Path, log_path: &Path) -> Vec<String> {
    vec![
        "/VERYSILENT".to_string(),
        "/SUPPRESSMSGBOXES".to_string(),
        "/NORESTART".to_string(),
        format!("/LOG={}", log_path.display()),
        format!("/DIR={}", install_dir.display()),
    ]
}

/// Stateless-правило спеки: оставить только каталоги с semver-именем СТРОГО
/// новее текущей версии; остальное (включая непарсящееся) удалить. Залоченное
/// пропускаем молча — доудалится при следующем старте.
pub fn cleanup_updates_dir(dir: &Path, current: &str) {
    let Ok(cur) = semver::Version::parse(current) else { return };
    let Ok(entries) = std::fs::read_dir(dir) else { return };
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let keep = semver::Version::parse(&name)
            .map(|v| v > cur)
            .unwrap_or(false);
        if !keep {
            let _ = std::fs::remove_dir_all(entry.path());
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

/// Директория загрузок: %LOCALAPPDATA%\KALI\updates
pub fn updates_dir() -> PathBuf {
    dirs::data_local_dir()
        .unwrap_or_else(std::env::temp_dir)
        .join("KALI")
        .join("updates")
}
```

В `src-tauri/src/backend/mod.rs` добавить `pub mod updater;` (рядом с существующими `pub mod ...` — сохранить алфавитный порядок, если он там есть).

- [ ] **Step 5: Прогнать тесты**

Run: `cd src-tauri; cargo test --test updater_core` → все PASS.

- [ ] **Step 6: Commit**

```bash
git add src-tauri/Cargo.toml src-tauri/Cargo.lock src-tauri/src/backend/updater.rs src-tauri/src/backend/mod.rs src-tauri/tests/updater_core.rs
git commit -m "feat(updater): manifest parsing, semver gate, install args, cleanup rule"
```

### Task 2: SHA-256 + скачивание с резюмом (против axum-мока)

**Files:**
- Modify: `src-tauri/src/backend/updater.rs`
- Test: `src-tauri/tests/updater_download.rs`

- [ ] **Step 1: Написать падающие тесты**

`src-tauri/tests/updater_download.rs`:

```rust
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
```

- [ ] **Step 2: Запустить — падают** (`cargo test --test updater_download` → compile error)

- [ ] **Step 3: Реализация в updater.rs**

```rust
use futures_util::StreamExt;
use sha2::{Digest, Sha256};
use tokio::io::AsyncWriteExt;

/// SHA-256 файла (потоково, файл может быть 2 GB).
pub async fn sha256_file(path: &Path) -> Result<String> {
    let mut file = tokio::fs::File::open(path).await?;
    let mut hasher = Sha256::new();
    let mut buf = vec![0u8; 1024 * 1024];
    loop {
        let n = tokio::io::AsyncReadExt::read(&mut file, &mut buf).await?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hex::encode(hasher.finalize()))
}

/// Скачать ассет в `dir/<asset.name>` (save-by-name — контракт DiskSpanning).
/// Резюм: len<size → Range; len==size → no-op (хэш проверяется отдельно);
/// len>size → удалить и заново. Сервер, игнорирующий Range (200), → truncate.
pub async fn download_asset(
    client: &reqwest::Client,
    asset: &Asset,
    dir: &Path,
    on_delta: &(dyn Fn(u64) + Send + Sync),
) -> Result<()> {
    tokio::fs::create_dir_all(dir).await?;
    let dest = dir.join(&asset.name);
    let mut have = tokio::fs::metadata(&dest).await.map(|m| m.len()).unwrap_or(0);
    if have > asset.size {
        tokio::fs::remove_file(&dest).await?;
        have = 0;
    }
    if have == asset.size {
        return Ok(());
    }
    let mut req = client.get(&asset.url);
    if have > 0 {
        req = req.header(reqwest::header::RANGE, format!("bytes={have}-"));
    }
    let resp = req.send().await?.error_for_status()?;
    let resumed = have > 0 && resp.status() == reqwest::StatusCode::PARTIAL_CONTENT;
    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .append(resumed)
        .write(true)
        .truncate(!resumed)
        .open(&dest)
        .await?;
    let mut stream = resp.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let bytes = chunk?;
        file.write_all(&bytes).await?;
        on_delta(bytes.len() as u64);
    }
    file.flush().await?;
    Ok(())
}
```

- [ ] **Step 4: Прогнать** — `cargo test --test updater_download` → PASS (и `--test updater_core` не сломан).

- [ ] **Step 5: Commit** — `feat(updater): resumable download + streaming sha256`

### Task 3: State-machine + оркестрация (check / download / verify)

**Files:**
- Modify: `src-tauri/src/backend/updater.rs`
- Test: `src-tauri/tests/updater_flow.rs`

- [ ] **Step 1: Падающие тесты**

`src-tauri/tests/updater_flow.rs` — мок сервит и манифест, и ассеты:

```rust
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
```

- [ ] **Step 2: Запустить — падают**

- [ ] **Step 3: Реализация state-machine в updater.rs**

```rust
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::{Mutex, Notify};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Phase {
    Idle,
    Available,
    Downloading,
    Ready,
    Installing,
    Error,
}

#[derive(Debug, Clone, Serialize)]
pub struct Snapshot {
    pub phase: Phase,
    pub current: String,
    pub available: Option<Manifest>,
    pub total: u64,
    pub downloaded: u64,
    pub error: Option<String>,
}

/// Мутабельное состояние под Mutex; прогресс — отдельным атомиком, потому что
/// колбэк скачивания синхронный (Fn(u64), без await) и дёргается очень часто.
struct Inner {
    phase: Phase,
    available: Option<Manifest>,
    total: u64,
    error: Option<String>,
}

pub struct Updater {
    inner: Mutex<Inner>,
    downloaded: AtomicU64,
    current: String,
    updates_root: PathBuf,
    manifest_url: String,
    client: reqwest::Client,
    terminal: Notify,
}

impl Updater {
    pub fn new(updates_root: PathBuf, current: &str) -> Arc<Self> {
        Self::with_url(updates_root, current, manifest_url())
    }

    /// Тесты/E2E: тот же конструктор, только явный URL (loopback-http валиден).
    pub fn new_for_tests(updates_root: PathBuf, current: &str, url: &str) -> Arc<Self> {
        Self::with_url(updates_root, current, url.to_string())
    }

    fn with_url(updates_root: PathBuf, current: &str, manifest_url: String) -> Arc<Self> {
        Arc::new(Self {
            inner: Mutex::new(Inner {
                phase: Phase::Idle,
                available: None,
                total: 0,
                error: None,
            }),
            downloaded: AtomicU64::new(0),
            current: current.to_string(),
            updates_root,
            manifest_url,
            client: reqwest::Client::new(),
            terminal: Notify::new(),
        })
    }

    pub async fn snapshot(&self) -> Snapshot {
        let s = self.inner.lock().await;
        Snapshot {
            phase: s.phase,
            current: self.current.clone(),
            available: s.available.clone(),
            total: s.total,
            downloaded: self.downloaded.load(Ordering::Relaxed).min(s.total),
            error: s.error.clone(),
        }
    }

    /// Тест-хелпер: дождаться Ready|Error после start_download.
    /// Notify-семантика: notify_waiters() будит только ENABLED-фьючи —
    /// notified() надо запиннить и .enable() ДО проверки фазы, иначе
    /// lost-wakeup (паттерн из доков tokio::sync::Notify).
    pub async fn wait_terminal(&self) {
        loop {
            let notified = self.terminal.notified();
            tokio::pin!(notified);
            notified.as_mut().enable();
            {
                let s = self.inner.lock().await;
                if matches!(s.phase, Phase::Ready | Phase::Error) {
                    return;
                }
            }
            notified.await;
        }
    }

    /// Проверка манифеста. Любая ошибка (сеть/JSON) = тихий Idle (лог, не error).
    /// Фазы Downloading/Ready/Installing никогда не трогаются (N+2 в процессе
    /// N+1 — игнор до завершения цикла, спека §Данные).
    pub async fn check(&self) -> Snapshot {
        let result: Result<Manifest> = async {
            let raw = self
                .client
                .get(&self.manifest_url)
                .timeout(std::time::Duration::from_secs(15))
                .send()
                .await?
                .error_for_status()?
                .text()
                .await?;
            parse_manifest(&raw)
        }
        .await;

        {
            let mut s = self.inner.lock().await;
            match result {
                Ok(m) if is_newer(&self.current, &m.version) => {
                    if matches!(s.phase, Phase::Idle | Phase::Available) {
                        s.total = m.total_size();
                        s.available = Some(m);
                        s.phase = Phase::Available;
                    }
                }
                Ok(_) => {
                    // манифест откатился/сравнялся — убрать устаревший баннер
                    if s.phase == Phase::Available {
                        s.phase = Phase::Idle;
                        s.available = None;
                    }
                }
                Err(e) => tracing::debug!("updater check skipped: {e:#}"),
            }
        }
        self.snapshot().await
    }

    /// Свободное место: суммарный size × 2 (download + in-place overwrite, спека).
    fn disk_ok(&self, needed: u64) -> bool {
        fs4::available_space(&self.updates_root)
            .or_else(|_| fs4::available_space(self.updates_root.parent().unwrap_or(Path::new("."))))
            .map(|free| free >= needed.saturating_mul(2))
            .unwrap_or(true) // не смогли измерить — не блокируем
    }

    pub async fn start_download(self: &Arc<Self>) {
        let manifest = {
            let mut s = self.inner.lock().await;
            let Some(m) = s.available.clone() else { return };
            if matches!(s.phase, Phase::Downloading | Phase::Ready | Phase::Installing) {
                return;
            }
            if !self.disk_ok(m.total_size()) {
                s.phase = Phase::Error;
                s.error = Some(format!(
                    "Недостаточно места: нужно ~{} ГБ свободного",
                    m.total_size() * 2 / 1_000_000_000
                ));
                self.terminal.notify_waiters();
                return;
            }
            s.phase = Phase::Downloading;
            s.error = None;
            self.downloaded.store(0, Ordering::Relaxed);
            m
        };
        let this = Arc::clone(self);
        tokio::spawn(async move { this.run_download(manifest).await });
    }

    async fn run_download(self: Arc<Self>, m: Manifest) {
        let dir = self.updates_root.join(&m.version);
        let result: Result<()> = async {
            // учесть уже скачанное (резюм) в прогрессе
            for a in &m.assets {
                let pre = tokio::fs::metadata(dir.join(&a.name))
                    .await
                    .map(|md| md.len().min(a.size))
                    .unwrap_or(0);
                self.downloaded.fetch_add(pre, Ordering::Relaxed);
            }
            for a in &m.assets {
                let counter = &self.downloaded;
                download_asset(&self.client, a, &dir, &|d| {
                    counter.fetch_add(d, Ordering::Relaxed);
                })
                .await?;
            }
            for a in &m.assets {
                let path = dir.join(&a.name);
                let got = sha256_file(&path).await?;
                if !got.eq_ignore_ascii_case(&a.sha256) {
                    let _ = tokio::fs::remove_file(&path).await;
                    bail!("SHA-256 не совпал для {}", a.name);
                }
            }
            Ok(())
        }
        .await;

        {
            let mut s = self.inner.lock().await;
            match result {
                Ok(()) => s.phase = Phase::Ready,
                Err(e) => {
                    s.phase = Phase::Error;
                    s.error = Some(format!("{e:#}"));
                }
            }
        }
        self.terminal.notify_waiters();
    }
}
```

- [ ] **Step 4: Прогнать** `cargo test --test updater_flow` → PASS; `--test updater_core --test updater_download` не сломаны.

- [ ] **Step 5: Commit** — `feat(updater): state machine check→download→verify`

## Chunk 2: Транспорт + UI

### Task 4: install + HTTP-роуты + wiring в http.rs

**Files:**
- Modify: `src-tauri/src/backend/updater.rs` (install)
- Modify: `src-tauri/src/backend/http.rs` (роуты + Extension-слой; в репо НЕТ AppState — стейт роутера это `Arc<EventBus>` через `.with_state(bus)`, остальные хэндлы инжектятся `.layer(Extension(...))` в `router_full(...)`)
- Modify: `src-tauri/src/backend/mod.rs` (cleanup при старте в `serve()`)
- Create: `src-tauri/tests/common/mod.rs` (общий release-мок из Task 3; пометить хелперы `#[allow(dead_code)]` — каждый тест-бинарь компилирует common независимо и использует не всё)
- Test: `src-tauri/tests/updater_install.rs`, `src-tauri/tests/updater_routes.rs`

- [ ] **Step 1: Падающие тесты**

`src-tauri/tests/updater_install.rs`:

```rust
//! install: пред-инсталльная ре-верификация + spawn стаба с точными аргументами.
use kali_desktop::backend::updater::{Phase, Updater};
// (переиспользуй spawn_release_srv из updater_flow.rs — вынеси в tests/common/mod.rs,
//  либо продублируй маленький мок здесь; ниже предполагается общий helper)

#[tokio::test]
async fn install_reverifies_and_spawns_stub_with_exact_args() {
    let base = common::spawn_release_srv(false).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", &format!("{base}/latest.json"));
    u.check().await;
    u.start_download().await;
    u.wait_terminal().await;
    assert_eq!(u.snapshot().await.phase, Phase::Ready);

    // Стаб-«инсталятор»: .cmd пишет свои аргументы в файл и выходит.
    let args_out = tmp.path().join("args.txt");
    let stub = tmp.path().join("stub.cmd");
    std::fs::write(&stub, format!("@echo %* > \"{}\"\n", args_out.display())).unwrap();

    let install_dir = tmp.path().join("install");
    std::fs::create_dir(&install_dir).unwrap();
    u.install_with(&stub, &install_dir, /*exit_process=*/ false).await.unwrap();

    // stub отработал асинхронно — подождать файл
    for _ in 0..50 {
        if args_out.exists() { break; }
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    }
    let args = std::fs::read_to_string(&args_out).unwrap();
    assert!(args.contains("/VERYSILENT"));
    assert!(args.contains("/SUPPRESSMSGBOXES"));
    assert!(args.contains("/NORESTART"));
    assert!(args.contains("install.log"));
    assert!(args.contains(&install_dir.display().to_string()));
}

#[tokio::test]
async fn install_fails_if_file_corrupted_after_ready() {
    let base = common::spawn_release_srv(false).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", &format!("{base}/latest.json"));
    u.check().await;
    u.start_download().await;
    u.wait_terminal().await;
    // портим файл после Ready (антивирус/чистка диска между ready и кликом)
    let f = tmp.path().join("9.9.9").join("KALI-Premium-Setup-9.9.9.exe");
    std::fs::write(&f, b"corrupted").unwrap();
    let stub = tmp.path().join("stub.cmd");
    std::fs::write(&stub, "@echo x\n").unwrap();
    let err = u
        .install_with(&stub, tmp.path(), false)
        .await
        .unwrap_err();
    assert!(err.to_string().contains("SHA-256"));
    assert_eq!(u.snapshot().await.phase, Phase::Error);
}
```

Вынести мок из Task 3 в `src-tauri/tests/common/mod.rs` (`pub async fn spawn_release_srv(...)`), в обоих тест-файлах `mod common;`.

- [ ] **Step 2: Запустить — падают**

- [ ] **Step 3: Реализация install в updater.rs**

```rust
impl Updater {
    /// Прод-путь: setup из скачанной директории, install_dir = родитель текущего exe,
    /// затем выход процесса (инсталятор перезапустит апп — .iss silent-ветка).
    pub async fn install(self: &Arc<Self>) -> Result<()> {
        let setup = {
            let s = self.inner.lock().await;
            let m = s.available.clone().context("нет скачанного обновления")?;
            self.updates_root
                .join(&m.version)
                .join(&m.assets.first().context("пустой манифест")?.name)
        };
        let exe = std::env::current_exe().context("current_exe")?;
        let install_dir = exe.parent().context("exe без родителя")?.to_path_buf();
        self.install_with(&setup, &install_dir, true).await
    }

    /// Тестируемое ядро: ре-верификация → spawn detached → (опц.) выход.
    pub async fn install_with(
        self: &Arc<Self>,
        setup_exe: &Path,
        install_dir: &Path,
        exit_process: bool,
    ) -> Result<()> {
        let m = {
            let mut s = self.inner.lock().await;
            let m = s.available.clone().context("нет доступного обновления")?;
            if s.phase != Phase::Ready {
                bail!("обновление не готово (phase={:?})", s.phase);
            }
            s.phase = Phase::Installing;
            m
        };
        let dir = self.updates_root.join(&m.version);
        // Пред-инсталльная ре-верификация (спека: между ready и кликом — часы)
        for a in &m.assets {
            let p = dir.join(&a.name);
            let ok = sha256_file(&p).await.map(|h| h.eq_ignore_ascii_case(&a.sha256));
            if !matches!(ok, Ok(true)) {
                let _ = tokio::fs::remove_file(&p).await;
                let mut s = self.inner.lock().await;
                s.phase = Phase::Error;
                s.error = Some(format!("SHA-256 не совпал перед установкой: {}", a.name));
                bail!("SHA-256 не совпал перед установкой: {}", a.name);
            }
        }
        let log = dir.join("install.log");
        let args = build_install_args(setup_exe, install_dir, &log);
        // .cmd/.bat нельзя спавнить напрямую (CreateProcess ждёт PE-бинарь) —
        // оборачиваем в `cmd /c`. Прод всегда .exe; ветка нужна тест-стабам.
        let is_batch = setup_exe
            .extension()
            .map(|e| e.eq_ignore_ascii_case("cmd") || e.eq_ignore_ascii_case("bat"))
            .unwrap_or(false);
        let mut cmd = if is_batch {
            let mut c = std::process::Command::new("cmd.exe");
            c.arg("/c").arg(setup_exe);
            c
        } else {
            std::process::Command::new(setup_exe)
        };
        cmd.args(&args);
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const DETACHED_PROCESS: u32 = 0x0000_0008;
            const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
            cmd.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
        }
        cmd.spawn().context("не удалось запустить инсталятор")?;
        if exit_process {
            tokio::spawn(async {
                tokio::time::sleep(std::time::Duration::from_millis(700)).await;
                std::process::exit(0);
            });
        }
        Ok(())
    }
}
```

- [ ] **Step 4: Роуты + wiring (Extension-паттерн, как pipeline/skills/catalog)**

В репо НЕТ AppState: стейт роутера — `Arc<EventBus>` (`.with_state(bus)`), остальные хэндлы инжектятся `.layer(Extension(...))` внутри `router_full(bus, pipeline, skills, catalog)` (см. http.rs ~651-654). Делаем так же:

1. В `router_full` (внутри, БЕЗ изменения сигнатуры — не рябить 3 обёртки и их тест-коллеров) сконструировать и заинжектить апдейтер:

```rust
// внутри router_full, рядом с существующими .layer(Extension(...)):
.layer(Extension(crate::backend::updater::Updater::new(
    crate::backend::updater::updates_dir(),
    env!("CARGO_PKG_VERSION"),
)))
```

2. Роуты (рядом с существующими, до `/ws`):

```rust
.route("/updater/status", get(updater_status))
.route("/updater/check", post(updater_check))
.route("/updater/download", post(updater_download))
.route("/updater/install", post(updater_install))
```

3. Хендлеры (сигнатуры — как у соседей с `Extension<Arc<...>>`):

```rust
use crate::backend::updater;

async fn updater_status(Extension(u): Extension<Arc<updater::Updater>>) -> Json<updater::Snapshot> {
    Json(u.snapshot().await)
}
async fn updater_check(Extension(u): Extension<Arc<updater::Updater>>) -> Json<updater::Snapshot> {
    Json(u.check().await)
}
async fn updater_download(Extension(u): Extension<Arc<updater::Updater>>) -> Json<updater::Snapshot> {
    u.start_download().await;
    Json(u.snapshot().await)
}
async fn updater_install(
    Extension(u): Extension<Arc<updater::Updater>>,
) -> (StatusCode, Json<serde_json::Value>) {
    match u.install().await {
        Ok(()) => (StatusCode::OK, Json(serde_json::json!({"status": "installing"}))),
        Err(e) => (
            StatusCode::CONFLICT,
            Json(serde_json::json!({"status": "error", "message": e.to_string()})),
        ),
    }
}
```

4. Cleanup при старте — в `serve()` в `src-tauri/src/backend/mod.rs` (~строка 62), один вызов до/рядом с построением роутера:

```rust
crate::backend::updater::cleanup_updates_dir(
    &crate::backend::updater::updates_dir(),
    env!("CARGO_PKG_VERSION"),
);
```

- [ ] **Step 5: Smoke-тест роутов через auth-обёрнутый роутер**

`src-tauri/tests/updater_routes.rs` — ВАЖНО: `app()` в auth_middleware.rs строит СВОЙ мини-роутер без updater-роутов — копировать оттуда только `temp_token()`/`TOKEN_ENV_LOCK` и инжекцию `ConnectInfo`; роутер брать НАСТОЯЩИЙ (`http::router()` — legacy-конструктор для state-free контрактных тестов):

```rust
//! /updater/status отвечает через реальный auth-обёрнутый роутер —
//! ловит ошибки wiring/сериализации, невидимые для cargo check.
use std::net::SocketAddr;
use std::sync::Mutex;

use axum::{body::Body, extract::ConnectInfo, http::Request};
use tower::ServiceExt; // oneshot

use kali_desktop::backend::auth::{self, ControlPlaneToken};
use kali_desktop::backend::http;

static TOKEN_ENV_LOCK: Mutex<()> = Mutex::new(());

fn temp_token() -> (ControlPlaneToken, tempfile::TempDir) {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("control-plane-token");
    let token = {
        let _guard = TOKEN_ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        std::env::set_var("KALI_TOKEN_FILE", &path);
        auth::load_or_create().expect("create token")
    };
    (token, dir)
}

#[tokio::test]
async fn updater_status_responds_idle_via_real_router() {
    let (token, _dir) = temp_token();
    let app = auth::with_auth(http::router(), token);
    let peer: SocketAddr = "127.0.0.1:54321".parse().unwrap(); // loopback → auth-exempt
    let mut req = Request::builder()
        .uri("/updater/status")
        .body(Body::empty())
        .unwrap();
    req.extensions_mut().insert(ConnectInfo(peer)); // oneshot не заполняет ConnectInfo сам
    let res = app.oneshot(req).await.unwrap();
    assert_eq!(res.status(), axum::http::StatusCode::OK);
    let body = axum::body::to_bytes(res.into_body(), 64 * 1024).await.unwrap();
    let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(v["phase"], "idle");
    assert!(!v["current"].as_str().unwrap().is_empty());
}
```

(Если `http::router()` не инжектит updater-Extension — значит Extension добавлен не в общий конструктор; правь wiring, а не тест: слой должен жить там, где его получают ВСЕ варианты роутера, включая legacy `router()`.)

- [ ] **Step 6: Прогнать всё** — `cargo test --test updater_install --test updater_flow --test updater_core --test updater_download --test updater_routes` PASS + `cargo check --lib` чистый.

- [ ] **Step 7: Commit** — `feat(updater): install with pre-spawn reverify + /updater/* control-plane routes`

### Task 5: updaterStore + endpoints

**Files:**
- Modify: `ui/src/api/endpoints.ts` (4 записи в RUST_ENDPOINTS)
- Create: `ui/src/stores/updaterStore.ts`
- Test: `ui/src/stores/__tests__/updaterStore.test.ts`

- [ ] **Step 1: Падающий тест**

```ts
// ui/src/stores/__tests__/updaterStore.test.ts
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stopPollForTests, useUpdaterStore } from "../updaterStore";

function snap(partial: Record<string, unknown> = {}) {
  return {
    phase: "idle", current: "1.0.0-rc1", available: null,
    total: 0, downloaded: 0, error: null, ...partial,
  };
}

describe("updaterStore", () => {
  beforeEach(() => {
    useUpdaterStore.setState(useUpdaterStore.getInitialState());
    stopPollForTests();       // упавший тест не должен утекать интервалом в следующий
    vi.unstubAllGlobals();    // restoreAllMocks НЕ снимает stubGlobal
  });

  it("check stores snapshot from POST /updater/check", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(
      snap({ phase: "available", available: { version: "1.0.1", notes: "n", assets: [], pub_date: "" }, total: 100 }),
    ))));
    await useUpdaterStore.getState().check();
    const s = useUpdaterStore.getState();
    expect(s.phase).toBe("available");
    expect(s.available?.version).toBe("1.0.1");
  });

  it("check failure is silent (stays idle, no error)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await useUpdaterStore.getState().check();
    const s = useUpdaterStore.getState();
    expect(s.phase).toBe("idle");
    expect(s.error).toBeNull();
  });

  it("download starts polling until terminal phase", async () => {
    vi.useFakeTimers();
    const phases = [
      snap({ phase: "downloading", total: 100, downloaded: 50 }),
      snap({ phase: "ready", total: 100, downloaded: 100 }),
    ];
    let call = 0;
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify(phases[Math.min(call++, phases.length - 1)]))));
    await useUpdaterStore.getState().download(); // POST → downloading
    expect(useUpdaterStore.getState().phase).toBe("downloading");
    await vi.advanceTimersByTimeAsync(800);      // первый poll → ready
    expect(useUpdaterStore.getState().phase).toBe("ready");
    await vi.advanceTimersByTimeAsync(2000);     // poll остановлен
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(2);
    vi.useRealTimers();
  });

  it("dismiss hides banner until next available version", () => {
    useUpdaterStore.setState({ phase: "available" });
    useUpdaterStore.getState().dismiss();
    expect(useUpdaterStore.getState().dismissed).toBe(true);
  });
});
```

- [ ] **Step 2: Запустить** `cd ui; pnpm exec vitest run src/stores/__tests__/updaterStore.test.ts` → FAIL.

- [ ] **Step 3: Реализация**

`ui/src/api/endpoints.ts` — в конец `RUST_ENDPOINTS`:

```ts
  // Auto-update — живёт целиком на Rust control-plane (:3006)
  { method: "GET", path: "/updater/status" },
  { method: "POST", path: "/updater/check" },
  { method: "POST", path: "/updater/download" },
  { method: "POST", path: "/updater/install" },
```

`ui/src/stores/updaterStore.ts`:

```ts
import { create } from "zustand";
import { resolveApiUrl } from "../api/endpoints";

export type UpdaterPhase =
  | "idle" | "available" | "downloading" | "ready" | "installing" | "error";

export interface UpdaterManifest {
  version: string;
  pub_date: string;
  notes: string;
  assets: { name: string; url: string; sha256: string; size: number }[];
}

interface UpdaterSnapshot {
  phase: UpdaterPhase;
  current: string;
  available: UpdaterManifest | null;
  total: number;
  downloaded: number;
  error: string | null;
}

interface UpdaterState extends UpdaterSnapshot {
  dismissed: boolean;
  check: () => Promise<void>;
  download: () => Promise<void>;
  install: () => Promise<void>;
  dismiss: () => void;
}

const POLL_MS = 700;
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function callUpdater(path: string, method: "GET" | "POST"): Promise<UpdaterSnapshot> {
  const res = await fetch(resolveApiUrl(path, method), { method });
  if (!res.ok) throw new Error(`updater ${path}: ${res.status}`);
  return res.json();
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/** Тест-хук: сбросить поллинг между тестами (см. beforeEach в тестах стора). */
export function stopPollForTests() {
  stopPoll();
}

export const useUpdaterStore = create<UpdaterState>((set, get) => ({
  phase: "idle",
  current: "",
  available: null,
  total: 0,
  downloaded: 0,
  error: null,
  dismissed: false,

  // Оффлайн/недоступный backend = тихий пропуск (спека)
  check: async () => {
    try {
      const snap = await callUpdater("/updater/check", "POST");
      const prev = get().available?.version;
      set({ ...snap, dismissed: snap.available?.version === prev ? get().dismissed : false });
    } catch { /* silent */ }
  },

  download: async () => {
    try {
      const snap = await callUpdater("/updater/download", "POST");
      set(snap);
      stopPoll();
      pollTimer = setInterval(async () => {
        try {
          const s = await callUpdater("/updater/status", "GET");
          set(s);
          if (s.phase !== "downloading") stopPoll();
        } catch { /* держим последний снапшот */ }
      }, POLL_MS);
    } catch { /* silent */ }
  },

  install: async () => {
    try {
      set({ phase: "installing" });
      await callUpdater("/updater/install", "POST");
      // дальше апп закроет Rust — UI ничего не делает
    } catch {
      set({ phase: "error", error: "Не удалось запустить установку — скачай релиз вручную" });
    }
  },

  dismiss: () => set({ dismissed: true }),
}));
```

- [ ] **Step 4: Прогнать** — тест PASS; также `pnpm exec vitest run` целиком (endpoints-тесты не сломаны).

- [ ] **Step 5: Commit** — `feat(ui): updater store + control-plane endpoints`

### Task 6: UpdateBanner + монтирование в App

**Files:**
- Create: `ui/src/components/UpdateBanner.tsx`
- Modify: `ui/src/App.tsx` (mount + чек на старте + 24ч интервал)
- Test: `ui/src/__tests__/UpdateBanner.test.tsx`

- [ ] **Step 1: Падающий тест**

```tsx
// ui/src/__tests__/UpdateBanner.test.tsx
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { UpdateBanner } from "../components/UpdateBanner";
import { useUpdaterStore } from "../stores/updaterStore";

const manifest = {
  version: "1.0.1", pub_date: "", notes: "Исправления голоса",
  assets: [{ name: "s.exe", url: "", sha256: "", size: 4_200_000_000 }],
};

describe("UpdateBanner", () => {
  beforeEach(() => useUpdaterStore.setState(useUpdaterStore.getInitialState()));

  it("renders nothing when idle", () => {
    const { container } = render(<UpdateBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("shows version, size and notes when available", () => {
    useUpdaterStore.setState({ phase: "available", available: manifest, total: 4_200_000_000 });
    render(<UpdateBanner />);
    expect(screen.getByText(/1\.0\.1/)).toBeInTheDocument();
    expect(screen.getByText(/4[.,]2/)).toBeInTheDocument(); // размер в ГБ
    expect(screen.getByRole("button", { name: /скачать/i })).toBeInTheDocument();
  });

  it("shows progress percent while downloading", () => {
    useUpdaterStore.setState({ phase: "downloading", available: manifest, total: 100, downloaded: 37 });
    render(<UpdateBanner />);
    expect(screen.getByText(/37\s*%/)).toBeInTheDocument();
  });

  it("shows restart button when ready", () => {
    useUpdaterStore.setState({ phase: "ready", available: manifest });
    render(<UpdateBanner />);
    expect(screen.getByRole("button", { name: /перезапустить/i })).toBeInTheDocument();
  });

  it("shows error with retry", () => {
    useUpdaterStore.setState({ phase: "error", available: manifest, error: "Обрыв сети" });
    render(<UpdateBanner />);
    expect(screen.getByText(/обрыв сети/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /продолжить/i })).toBeInTheDocument();
  });

  it("hidden when dismissed", () => {
    useUpdaterStore.setState({ phase: "available", available: manifest, dismissed: true });
    const { container } = render(<UpdateBanner />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Запустить — FAIL**

- [ ] **Step 3: Реализация**

`ui/src/components/UpdateBanner.tsx` (стиль — как соседние баннеры в App.tsx: css-переменные `--j-*`, без новых зависимостей):

```tsx
import { useUpdaterStore } from "../stores/updaterStore";

function gb(bytes: number): string {
  return (bytes / 1_000_000_000).toFixed(1).replace(".", ",");
}

/** Ненавязчивый баннер обновления (спека 2026-07-14-auto-update-design.md).
    Рендерится только в фазах available/downloading/ready/error и пока не dismissed. */
export function UpdateBanner() {
  const s = useUpdaterStore();
  if (s.dismissed || s.phase === "idle" || s.phase === "installing" || !s.available) return null;

  const pct = s.total > 0 ? Math.floor((s.downloaded / s.total) * 100) : 0;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border p-4 shadow-lg"
      style={{ background: "var(--j-surface, #111)", borderColor: "var(--j-border, #333)", color: "var(--j-text, #eee)" }}
      role="status"
    >
      {s.phase === "available" && (
        <>
          <div className="font-semibold">Доступна KALI {s.available.version}</div>
          {s.available.notes && (
            <div className="mt-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}>{s.available.notes}</div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.download()}>
              Скачать ({gb(s.total)} ГБ)
            </button>
            <button className="px-2 py-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}
              onClick={s.dismiss}>
              Позже
            </button>
          </div>
        </>
      )}
      {s.phase === "downloading" && (
        <>
          <div className="font-semibold">Скачивание KALI {s.available.version}… {pct} %</div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--j-border, #333)" }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--j-accent, #2563eb)" }} />
          </div>
        </>
      )}
      {s.phase === "ready" && (
        <>
          <div className="font-semibold">KALI {s.available.version} готова к установке</div>
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.install()}>
              Перезапустить и обновить
            </button>
            <button className="px-2 py-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }} onClick={s.dismiss}>
              Позже
            </button>
          </div>
        </>
      )}
      {s.phase === "error" && (
        <>
          <div className="font-semibold">Обновление прервано</div>
          <div className="mt-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}>{s.error}</div>
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.download()}>
              Продолжить
            </button>
            <a className="px-2 py-1 text-sm underline" style={{ color: "var(--j-text-dim, #aaa)" }}
              href="https://github.com/VasilyKolbenev/kali-ai-os/releases" target="_blank" rel="noreferrer">
              Скачать вручную
            </a>
          </div>
        </>
      )}
    </div>
  );
}
```

`ui/src/App.tsx`: импорт + `<UpdateBanner />` в главный return (рядом с существующими глобальными оверлеями) + каденс:

```tsx
import { UpdateBanner } from "./components/UpdateBanner";
import { useUpdaterStore } from "./stores/updaterStore";

// внутри App():
const updaterCheck = useUpdaterStore((s) => s.check);
useEffect(() => {
  void updaterCheck();                                  // на старте
  const id = setInterval(() => void updaterCheck(), 24 * 3600 * 1000); // раз в сутки
  return () => clearInterval(id);
}, [updaterCheck]);
```

`<UpdateBanner />` вставить в главный return App (после Sidebar/основного контента, на верхнем уровне flex-контейнера).

- [ ] **Step 4: Прогнать** — `pnpm exec vitest run` целиком PASS.

- [ ] **Step 5: Commit** — `feat(ui): update banner with download progress + daily check`

## Chunk 3: installer, publishing, финал

### Task 7: .iss — silent-перезапуск + ожидание процессов

**Files:**
- Modify: `scripts/installer_premium.iss`

- [ ] **Step 1: Правки**

В `[Run]` после существующей postinstall-строки:

```ini
; Auto-update: тихая установка перезапускает апп сама (обычная установка
; использует postinstall-строку выше; skipifnotsilent исключает двойной запуск).
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Flags: nowait skipifnotsilent
```

В `[Code]` заменить `InitializeSetup` (taskkill ждёт только сам taskkill.exe, не release хэндлов — гонка kill→copy из спеки):

```pascal
function ProcessRunning(const ExeName: string): Boolean;
var
  ResultCode: Integer;
begin
  // tasklist + find: find выходит с 0, если имя найдено (процесс жив)
  Exec('cmd.exe', '/c tasklist /FI "IMAGENAME eq ' + ExeName + '" | find /I "' + ExeName + '" > nul',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
  Waited: Integer;
begin
  Exec('taskkill.exe', '/IM kali-backend.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/IM kali-desktop.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Ждём реального исчезновения процессов (до ~10 с) — иначе file-in-use при копировании.
  Waited := 0;
  while (Waited < 10000) and (ProcessRunning('kali-backend.exe') or ProcessRunning('kali-desktop.exe')) do
  begin
    Sleep(500);
    Waited := Waited + 500;
  end;
  // Если процесс жив после таймаута — продолжаем; /SUPPRESSMSGBOXES авто-абортит
  // на file-in-use (принятый v1 fail-режим, спека «Инсталятор §2»).
  Result := True;
end;
```

- [ ] **Step 2: Проверка компиляции .iss**

Run: `& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer_premium.iss /O- /Q` — если ISCC нет по этому пути, найти через `Get-ChildItem "C:\Program Files (x86)" -Filter ISCC.exe -Recurse`. `/O-` отключает выходной файл (нужна только валидация синтаксиса; полная сборка требует premium_stage). Ожидаемо: без Pascal/синтакс-ошибок (может упасть на отсутствии `..\dist_premium\premium_stage` — это ОК, синтаксис проверяется до [Files]; если падает раньше компиляции кода — создать пустую premium_stage директорию).

- [ ] **Step 3: Commit** — `feat(installer): silent-mode relaunch + wait-for-process-exit before copy`

### Task 8: publish_release.py + тесты валидации

**Files:**
- Create: `scripts/publish_release.py`
- Create: `tests/scripts/conftest.py` (repo root → sys.path; без него CI-коллекция падает ImportError — `uv run pytest -m core_loop` КОЛЛЕКТИТ tests/scripts до применения маркеров, а scripts/ не пакет)
- Test: `tests/scripts/test_publish_release.py`

- [ ] **Step 1: Падающие тесты**

```python
# tests/scripts/test_publish_release.py
"""Валидация версий и генерация манифеста publish_release (gh/git не вызываются)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.publish_release import (
    build_manifest,
    collect_assets,
    validate_versions,
)


def _mk_dist(tmp: Path, ver: str) -> Path:
    d = tmp / "installer"
    d.mkdir()
    (d / f"KALI-Premium-Setup-{ver}.exe").write_bytes(b"exe-bytes")
    for i in (1, 2, 3):
        (d / f"KALI-Premium-Setup-{ver}-{i}.bin").write_bytes(b"bin" * i)
    return d


def _mk_repo(tmp: Path, tauri_ver: str, cargo_ver: str, iss_ver: str) -> Path:
    (tmp / "src-tauri").mkdir()
    (tmp / "scripts").mkdir()
    (tmp / "src-tauri" / "tauri.conf.json").write_text(
        json.dumps({"version": tauri_ver}), encoding="utf-8"
    )
    (tmp / "src-tauri" / "Cargo.toml").write_text(
        f'[package]\nname = "kali-desktop"\nversion = "{cargo_ver}"\n', encoding="utf-8"
    )
    (tmp / "scripts" / "installer_premium.iss").write_text(
        f'#define AppVersion "{iss_ver}"\n', encoding="utf-8"
    )
    return tmp


def test_validate_passes_when_all_versions_match(tmp_path: Path) -> None:
    repo = _mk_repo(tmp_path, "1.0.1", "1.0.1", "1.0.1")
    dist = _mk_dist(tmp_path, "1.0.1")
    assert validate_versions(repo, dist) == "1.0.1"


@pytest.mark.parametrize("field", ["tauri", "cargo", "iss", "files"])
def test_validate_hard_fails_on_any_mismatch(tmp_path: Path, field: str) -> None:
    vers = {"tauri": "1.0.1", "cargo": "1.0.1", "iss": "1.0.1"}
    file_ver = "1.0.1"
    if field == "files":
        file_ver = "9.9.9"
    else:
        vers[field] = "9.9.9"
    repo = _mk_repo(tmp_path, vers["tauri"], vers["cargo"], vers["iss"])
    dist = _mk_dist(tmp_path, file_ver)
    with pytest.raises(SystemExit):
        validate_versions(repo, dist)


def test_collect_assets_requires_exactly_setup_plus_bins(tmp_path: Path) -> None:
    dist = _mk_dist(tmp_path, "1.0.1")
    assets = collect_assets(dist, "1.0.1")
    names = [a.name for a in assets]
    assert names[0] == "KALI-Premium-Setup-1.0.1.exe"  # exe первым (манифест-контракт)
    assert len(names) == 4
    # отсутствие слайса = hard fail
    (dist / "KALI-Premium-Setup-1.0.1-2.bin").unlink()
    with pytest.raises(SystemExit):
        collect_assets(dist, "1.0.1")


def test_build_manifest_has_correct_hashes_urls_sizes(tmp_path: Path) -> None:
    dist = _mk_dist(tmp_path, "1.0.1")
    assets = collect_assets(dist, "1.0.1")
    m = build_manifest("1.0.1", "notes", assets, pub_date="2026-07-20T12:00:00Z")
    assert m["version"] == "1.0.1"
    a0 = m["assets"][0]
    assert a0["name"] == "KALI-Premium-Setup-1.0.1.exe"
    assert a0["url"] == (
        "https://github.com/VasilyKolbenev/kali-ai-os/releases/download/"
        "v1.0.1/KALI-Premium-Setup-1.0.1.exe"
    )
    assert a0["sha256"] == hashlib.sha256(b"exe-bytes").hexdigest()
    assert a0["size"] == len(b"exe-bytes")
    assert len(m["assets"]) == 4
```

- [ ] **Step 2: Запустить** `.venv\Scripts\python.exe -m pytest tests/scripts/test_publish_release.py -q` → FAIL (import).

- [ ] **Step 3: Реализация `scripts/publish_release.py`**

```python
"""Публикация релиза KALI: валидация версий → draft GH-релиз → ассеты → undraft →
коммит releases/latest.json (атомарный флип — клиенты видят версию последним шагом).

Использование (после build → frozen_smoke):
    .venv\\Scripts\\python.exe scripts\\publish_release.py --notes "Что нового"

Спека: docs/superpowers/specs/2026-07-14-auto-update-design.md §Публикация.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

log = logging.getLogger("publish_release")

REPO_SLUG = "VasilyKolbenev/kali-ai-os"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = REPO_ROOT / "dist_premium" / "installer"
MANIFEST_PATH = REPO_ROOT / "releases" / "latest.json"


@dataclass
class AssetFile:
    name: str
    path: Path


def _fail(msg: str) -> NoReturn:
    log.error(msg)
    raise SystemExit(1)


def _read_tauri_version(repo: Path) -> str:
    conf = json.loads((repo / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    return str(conf["version"])


def _read_cargo_version(repo: Path) -> str:
    text = (repo / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        _fail("Cargo.toml: version не найдена")
    return m.group(1)


def _read_iss_version(repo: Path) -> str:
    text = (repo / "scripts" / "installer_premium.iss").read_text(encoding="utf-8")
    m = re.search(r'#define AppVersion "([^"]+)"', text)
    if not m:
        _fail("installer_premium.iss: AppVersion не найден")
    return m.group(1)


def validate_versions(repo: Path, dist: Path) -> str:
    """Единство версии: tauri.conf == Cargo.toml == .iss == имена файлов.

    Расхождение = update-петля (апп обновился, считает себя старым) — hard fail.
    """
    tauri = _read_tauri_version(repo)
    cargo = _read_cargo_version(repo)
    iss = _read_iss_version(repo)
    if not (tauri == cargo == iss):
        _fail(f"Версии расходятся: tauri.conf={tauri} Cargo.toml={cargo} iss={iss}")
    if not (dist / f"KALI-Premium-Setup-{tauri}.exe").exists():
        _fail(f"В {dist} нет KALI-Premium-Setup-{tauri}.exe — версия файлов иная?")
    return tauri


def collect_assets(dist: Path, version: str) -> list[AssetFile]:
    """Setup.exe + все .bin-слайсы; exe строго первым (контракт манифеста —
    Rust берёт assets[0] как исполняемый setup)."""
    exe = dist / f"KALI-Premium-Setup-{version}.exe"
    if not exe.exists():
        _fail(f"Нет {exe}")
    bins = sorted(dist.glob(f"KALI-Premium-Setup-{version}-*.bin"))
    if not bins:
        _fail("Не найдено ни одного .bin-слайса (DiskSpanning)")
    expected = {f"KALI-Premium-Setup-{version}-{i}.bin" for i in range(1, len(bins) + 1)}
    actual = {b.name for b in bins}
    if expected != actual:
        _fail(f"Слайсы не непрерывны: {sorted(actual)}")
    return [AssetFile(exe.name, exe)] + [AssetFile(b.name, b) for b in bins]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    version: str, notes: str, assets: list[AssetFile], pub_date: str | None = None
) -> dict:
    return {
        "version": version,
        "pub_date": pub_date or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": notes,
        "assets": [
            {
                "name": a.name,
                "url": f"https://github.com/{REPO_SLUG}/releases/download/v{version}/{a.name}",
                "sha256": _sha256(a.path),
                "size": a.path.stat().st_size,
            }
            for a in assets
        ],
    }


def _run(cmd: list[str]) -> None:
    log.info("$ %s", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)


def publish(version: str, notes: str, assets: list[AssetFile]) -> None:
    tag = f"v{version}"
    prerelease = ["--prerelease"] if "-" in version else []
    # Идемпотентность: битый draft с прошлого падения — пересоздать
    view = subprocess.run(
        ["gh", "release", "view", tag, "--json", "isDraft"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    if view.returncode == 0:
        if json.loads(view.stdout).get("isDraft"):
            log.info("Найден draft %s с прошлого запуска — удаляю и пересоздаю", tag)
            _run(["gh", "release", "delete", tag, "--yes"])
        else:
            _fail(f"Релиз {tag} уже опубликован")
    _run(["gh", "release", "create", tag, "--draft", "--title", f"KALI {version}",
          "--notes", notes, *prerelease])
    for a in assets:
        _run(["gh", "release", "upload", tag, str(a.path)])
    _run(["gh", "release", "edit", tag, "--draft=false"])


def flip_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _run(["git", "add", str(MANIFEST_PATH)])
    # pathspec: не подметать чужой staged-мусор в релизный коммит
    _run(["git", "commit", "-m", f"release: latest.json -> {manifest['version']}",
          "--", str(MANIFEST_PATH)])
    _run(["git", "push", "origin", "main"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", required=True, help="Release notes (RU, кратко)")
    args = parser.parse_args()
    version = validate_versions(REPO_ROOT, DIST_DIR)
    assets = collect_assets(DIST_DIR, version)
    manifest = build_manifest(version, args.notes, assets)
    publish(version, args.notes, assets)
    flip_manifest(manifest)  # ПОСЛЕДНИМ — атомарный флип
    log.info("Опубликовано: %s (%d ассетов)", version, len(assets))


if __name__ == "__main__":
    main()
```

Создать `tests/scripts/conftest.py` (ВАЖНО: без него `from scripts.publish_release import ...` падает ImportError при CI-коллекции — test_build_prune.py не случайно грузит скрипт через importlib):

```python
"""tests/scripts импортируют из scripts/ (не пакет) — кладём repo root в sys.path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
```


- [ ] **Step 4: Прогнать** — `pytest tests/scripts/test_publish_release.py -q` PASS.

- [ ] **Step 5: Commit** — `feat(release): publish_release.py — version unity, draft-first ordering, manifest flip`

### Task 9: CI-гейт для updater-тестов + релизная документация + финальный прогон

**Files:**
- Modify: `.github/workflows/ci.yml` (rust-джоб: cargo check НЕ запускает тесты — новые интеграционные тесты иначе никогда не бегут в CI)
- Modify: `docs/public-launch/2026-07-13-v1-rc1-test-checklist.md` (или актуальный релизный чеклист) — НЕ трогать чужие пункты, добавить раздел
- Полный прогон всех гейтов

**Примечание о версии:** Rust читает свою версию из `env!("CARGO_PKG_VERSION")` (Cargo.toml), спека называет источником tauri.conf.json — эквивалентно ТОЛЬКО потому, что `validate_versions` в publish-скрипте жёстко требует их равенства при каждом релизе; это осознанная связка, не случайность.

- [ ] **Step 0: CI — гонять updater-тесты (только их: сетевых/аудио-зависимостей нет)**

В `.github/workflows/ci.yml`, rust-джоб, после `Cargo check (lib)` добавить шаг (те же env/MSVC-обходы, что у check):

```yaml
      - name: Updater tests (network-free, no audio deps)
        run: cargo test --test updater_core --test updater_download --test updater_flow --test updater_install --test updater_routes
        working-directory: src-tauri
        env:
          CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER: link.exe
          # updater_* бинарники триггерят Windows Installer Detection (error 740);
          # RunAsInvoker shim обходит авто-elevation (защитно — на случай не-админ раннера).
          __COMPAT_LAYER: RunAsInvoker
```

(Полный `cargo test --tests` в CI НЕ включаем: voice/ML-тесты требуют аудио-устройств и тяжёлых артефактов раннера — это отдельное решение вне скоупа.)

- [ ] **Step 1: Дописать релизный ритуал**

В конец релизного чеклиста добавить раздел:

```markdown
## Auto-update (с v1.0.0-rc2+)
- [ ] `python scripts/publish_release.py --notes "..."` (после build → frozen_smoke)
- [ ] Живой прогон: предыдущая установленная версия → баннер → скачивание → тихая установка → перезапуск новой (обязательный релиз-гейт, аналог frozen_smoke)
- [ ] Прогон на потребительской RU-сети (raw.githubusercontent временами троттлится у RU-провайдеров)
```

- [ ] **Step 2: Полный прогон гейтов**

```
cd src-tauri; cargo test --test updater_core --test updater_download --test updater_flow --test updater_install --test updater_routes; cargo check --lib
cd ui; pnpm exec vitest run
.venv\Scripts\python.exe -m pytest tests/scripts/test_publish_release.py -q
.venv\Scripts\python.exe -m pytest -m core_loop -q
```

Ожидаемо: всё зелёное (kernel-suite не тронут этим планом — питон-код kernel не менялся).

- [ ] **Step 3: Commit + push**

```bash
git add -A
git commit -m "docs(release): auto-update publish + live-rehearsal gate in release ritual"
git push origin main
```

- [ ] **Step 4: Проверить CI зелёный** — `gh run watch $(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`

**Definition of Done (из спеки):** живой полноразмерный прогон (пункт 1 DoD) выполняется при СЛЕДУЮЩЕМ релизе (rc2) — первый релиз с апдейтером не может сам себя обновить; фиксируется в релизном чеклисте. Код-DoD: все тесты зелёные + CI зелёный + publish-скрипт валидирован тестами.
