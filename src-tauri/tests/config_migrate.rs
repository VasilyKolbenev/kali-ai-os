//! OPUS-301: a stored retired anthropic model id migrates to the active default
//! on config load, with the rest of the config preserved.
use kali_desktop::backend::config;

#[test]
fn load_from_migrates_retired_anthropic_model() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("kali.yaml");
    std::fs::write(
        &path,
        "llm:\n  \
         cloud_provider: anthropic\n  \
         cloud_model: claude-sonnet-4-20250514\n  \
         local_provider: ollama\n  \
         local_model: llama3\n  \
         auto_route: true\n",
    )
    .unwrap();

    let cfg = config::load_from(&path).unwrap();
    assert_eq!(cfg.llm.cloud_model, "claude-sonnet-5");
    assert_eq!(cfg.llm.cloud_provider, "anthropic");
    // untouched fields survive
    assert_eq!(cfg.llm.local_model, "llama3");
    assert!(cfg.llm.auto_route);
}

#[test]
fn load_from_leaves_active_model_untouched() {
    let tmp = tempfile::tempdir().unwrap();
    let path = tmp.path().join("kali.yaml");
    std::fs::write(
        &path,
        "llm:\n  \
         cloud_provider: anthropic\n  \
         cloud_model: claude-sonnet-5\n  \
         local_provider: ollama\n  \
         local_model: llama3\n  \
         auto_route: true\n",
    )
    .unwrap();

    let cfg = config::load_from(&path).unwrap();
    assert_eq!(cfg.llm.cloud_model, "claude-sonnet-5");
}
