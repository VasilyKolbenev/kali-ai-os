fn main() {
    // Capture short git commit for /version endpoint (best-effort).
    if let Ok(output) = std::process::Command::new("git")
        .args(["rev-parse", "--short", "HEAD"])
        .output()
    {
        if output.status.success() {
            let hash = String::from_utf8_lossy(&output.stdout).trim().to_string();
            println!("cargo:rustc-env=KALI_GIT_COMMIT={}", hash);
        }
    }
    println!("cargo:rerun-if-changed=../.git/HEAD");

    tauri_build::build()
}
