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
