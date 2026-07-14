//! Auto-update: манифест в репо → резюмируемое скачивание с GitHub Releases →
//! SHA-256 → тихий InnoSetup. Спека: docs/superpowers/specs/2026-07-14-auto-update-design.md
//! Транспорт — HTTP-роуты control-plane (:3006), см. http.rs.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Idle-таймаут между чанками загрузки: сброс на КАЖДЫЙ чанк, не на весь запрос —
/// многогигабайтная закачка не убивается за то, что идёт долго, только за молчание.
/// Дросселирование raw.githubusercontent/GitHub (риск №1 спеки) = тихий TCP-стап,
/// который иначе висит вечно (фаза залипает на Downloading до рестарта).
pub const DEFAULT_DOWNLOAD_IDLE_TIMEOUT: Duration = Duration::from_secs(60);

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

/// Классифицировать ошибку загрузки в RU-строку для баннера. Три класса:
/// SHA-256 (уже RU, сохраняем) → сеть/стап/таймаут → generic-fallback.
fn ru_download_error(e: &anyhow::Error) -> String {
    let chain = format!("{e:#}");
    // Ре-верификация не совпала — сообщение уже RU, отдаём как есть.
    if chain.contains("SHA-256") {
        return chain;
    }
    // Сеть/стап/таймаут: reqwest-ошибка либо наш watchdog-стап.
    let low = chain.to_lowercase();
    if e.downcast_ref::<reqwest::Error>().is_some()
        || low.contains("stalled")
        || low.contains("timeout")
        || low.contains("timed out")
        || low.contains("connect")
    {
        return "Соединение прервано во время загрузки — можно продолжить".to_string();
    }
    "Ошибка загрузки — можно продолжить".to_string()
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
/// Idle-таймаут между чанками — [`DEFAULT_DOWNLOAD_IDLE_TIMEOUT`].
pub async fn download_asset(
    client: &reqwest::Client,
    asset: &Asset,
    dir: &Path,
    on_delta: &(dyn Fn(u64) + Send + Sync),
) -> Result<()> {
    download_asset_with_idle(client, asset, dir, on_delta, DEFAULT_DOWNLOAD_IDLE_TIMEOUT).await
}

/// Ядро загрузки с инъектируемым idle-таймаутом (тест передаёт короткий, чтобы
/// не ждать реальные 60с при проверке стап-watchdog).
pub async fn download_asset_with_idle(
    client: &reqwest::Client,
    asset: &Asset,
    dir: &Path,
    on_delta: &(dyn Fn(u64) + Send + Sync),
    idle_timeout: Duration,
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
    loop {
        // Watchdog: тихий стап (нет чанка за idle_timeout) → Err, а не вечное
        // ожидание. Таймер сбрасывается на каждый успешный чанк.
        match tokio::time::timeout(idle_timeout, stream.next()).await {
            Err(_elapsed) => bail!(
                "download stalled: no data for {}s",
                idle_timeout.as_secs()
            ),
            Ok(None) => break,
            Ok(Some(chunk)) => {
                let bytes = chunk?;
                file.write_all(&bytes).await?;
                on_delta(bytes.len() as u64);
            }
        }
    }
    file.flush().await?;
    Ok(())
}

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
            // connect_timeout ловит мёртвый хост на этапе установки соединения
            // (idle-watchdog в download_asset покрывает стап уже в теле ответа).
            client: reqwest::Client::builder()
                .connect_timeout(Duration::from_secs(30))
                .build()
                .unwrap_or_else(|_| reqwest::Client::new()),
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
                    // Тех-детали (EN reqwest/anyhow-цепочка) — в лог; в баннер
                    // (snapshot.error) — только RU-строка (RU-user-facing конвенция).
                    tracing::warn!("updater download failed: {e:#}");
                    s.phase = Phase::Error;
                    s.error = Some(ru_download_error(&e));
                }
            }
        }
        self.terminal.notify_waiters();
    }

    /// Прод-путь: setup из скачанной директории, install_dir = родитель текущего exe,
    /// затем выход процесса (инсталятор перезапустит апп — .iss silent-ветка).
    pub async fn install(self: &Arc<Self>) -> Result<()> {
        let setup = {
            let s = self.inner.lock().await;
            let m = s.available.clone().context("нет скачанного обновления")?;
            let first = &m.assets.first().context("пустой манифест")?.name;
            // Прод-инвариант: первый ассет DiskSpanning — всегда setup.exe.
            // Голая .exe идёт в прямой spawn (cmd /c — только для тест-стабов).
            if !first.to_ascii_lowercase().ends_with(".exe") {
                bail!("первый ассет не .exe: {first}");
            }
            self.updates_root.join(&m.version).join(first)
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
                {
                    let mut s = self.inner.lock().await;
                    s.phase = Phase::Error;
                    s.error = Some(format!("SHA-256 не совпал перед установкой: {}", a.name));
                }
                self.terminal.notify_waiters();
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
        // Spawn может упасть (AV-лок на свежем setup.exe, отказ прав) — откатить
        // в Error, иначе фаза Installing залипнет навсегда (recovery-веток из неё
        // нет: check трогает только Idle|Available, start_download блокирует
        // Installing). available остаётся Some → повторное скачивание/retry живо.
        if let Err(e) = cmd.spawn().context("не удалось запустить инсталятор") {
            {
                let mut s = self.inner.lock().await;
                s.phase = Phase::Error;
                s.error = Some(format!("{e:#}"));
            }
            self.terminal.notify_waiters();
            return Err(e);
        }
        if exit_process {
            tokio::spawn(async {
                tokio::time::sleep(std::time::Duration::from_millis(700)).await;
                std::process::exit(0);
            });
        }
        Ok(())
    }
}
