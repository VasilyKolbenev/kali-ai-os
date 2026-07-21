//! install: пред-инсталльная ре-верификация + spawn стаба с точными аргументами.
use kali_desktop::backend::updater::{Phase, Updater};

mod common;

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
    u.install_with(&stub, &install_dir).await.unwrap();

    // stub отработал асинхронно — подождать файл
    for _ in 0..50 {
        if args_out.exists() {
            break;
        }
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
    let f = tmp
        .path()
        .join("9.9.9")
        .join("KALI-Premium-Setup-9.9.9.exe");
    std::fs::write(&f, b"corrupted").unwrap();
    let stub = tmp.path().join("stub.cmd");
    std::fs::write(&stub, "@echo x\n").unwrap();
    let err = u.install_with(&stub, tmp.path()).await.unwrap_err();
    assert!(err.to_string().contains("SHA-256"));
    assert_eq!(u.snapshot().await.phase, Phase::Error);
}

#[tokio::test]
async fn install_spawn_failure_rolls_back_to_error_and_is_recoverable() {
    let base = common::spawn_release_srv(false).await;
    let tmp = tempfile::tempdir().unwrap();
    let u = Updater::new_for_tests(tmp.path().into(), "1.0.0", &format!("{base}/latest.json"));
    u.check().await;
    u.start_download().await;
    u.wait_terminal().await;
    assert_eq!(u.snapshot().await.phase, Phase::Ready);

    // Ассеты в updates_root/9.9.9/ валидны → reverify проходит; но setup_exe
    // указывает на несуществующий файл → CreateProcess падает при spawn.
    let bogus = tmp.path().join("does-not-exist.exe");
    let err = u.install_with(&bogus, tmp.path()).await.unwrap_err();
    assert!(err.to_string().contains("инсталятор"), "err={err}");

    // Залипания в Installing нет — фаза Error, а обновление ещё доступно (retry жив).
    let snap = u.snapshot().await;
    assert_eq!(snap.phase, Phase::Error);
    assert!(snap.available.is_some());
}
