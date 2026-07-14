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
