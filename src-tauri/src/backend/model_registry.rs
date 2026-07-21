//! Provider model registry — Rust view of the shared machine-readable SoT
//! (`config/model_registry.json`), embedded at compile time (OPUS-301). No
//! network, no fs at runtime. Anthropic is the enforced provider this batch;
//! helpers are safe no-ops for any provider absent from the SoT.

use std::collections::HashMap;
use std::sync::OnceLock;

use serde::Deserialize;

/// Same JSON the Python/TS/Dart consumers read — single source of truth.
const REGISTRY_JSON: &str = include_str!("../../../config/model_registry.json");

#[derive(Debug, Deserialize)]
struct ProviderCfg {
    default: String,
    // Part of the parsed SoT contract (validates default ∈ models cross-language,
    // asserted in tests); Rust prod only needs default + retired.
    #[allow(dead_code)]
    models: Vec<String>,
    #[serde(default)]
    retired: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct Registry {
    providers: HashMap<String, ProviderCfg>,
}

fn registry() -> &'static Registry {
    static REG: OnceLock<Registry> = OnceLock::new();
    REG.get_or_init(|| {
        serde_json::from_str(REGISTRY_JSON).expect("config/model_registry.json is valid")
    })
}

fn provider(name: &str) -> Option<&'static ProviderCfg> {
    registry().providers.get(name)
}

/// Active default model for `provider`, or `None` if unmanaged.
pub fn default_model(provider_name: &str) -> Option<&'static str> {
    provider(provider_name).map(|c| c.default.as_str())
}

/// True iff `model` is a retired id for a managed `provider`.
pub fn is_retired(provider_name: &str, model: &str) -> bool {
    provider(provider_name)
        .map(|c| c.retired.iter().any(|r| r == model))
        .unwrap_or(false)
}

/// Migrate a retired `model` to the provider default. Returns
/// `(model, None)` when unmanaged/active, `(default, Some(warning))` when retired.
pub fn migrate(provider_name: &str, model: &str) -> (String, Option<String>) {
    if !is_retired(provider_name, model) {
        return (model.to_string(), None);
    }
    // is_retired => provider is managed => default exists.
    let def = default_model(provider_name).unwrap_or(model);
    let warn =
        format!("retired model {model:?} for provider {provider_name:?} migrated to {def:?}");
    (def.to_string(), Some(warn))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn anthropic_default_is_sonnet_5() {
        assert_eq!(default_model("anthropic"), Some("claude-sonnet-5"));
    }

    #[test]
    fn retired_ids_are_flagged_and_absent_from_active() {
        assert!(is_retired("anthropic", "claude-sonnet-4-20250514"));
        assert!(!is_retired("anthropic", "claude-sonnet-5"));
        let active = &registry().providers["anthropic"].models;
        for r in &registry().providers["anthropic"].retired {
            assert!(!active.contains(r), "retired {r} leaked into active");
        }
    }

    #[test]
    fn migrate_retired_to_default_with_warning() {
        let (m, w) = migrate("anthropic", "claude-sonnet-4-20250514");
        assert_eq!(m, "claude-sonnet-5");
        assert!(w.unwrap().contains("claude-sonnet-4-20250514"));
    }

    #[test]
    fn unmanaged_provider_is_noop() {
        assert_eq!(default_model("groq"), None);
        assert!(!is_retired("groq", "llama-3.3-70b-versatile"));
        assert_eq!(
            migrate("groq", "llama-3.3-70b-versatile"),
            ("llama-3.3-70b-versatile".to_string(), None)
        );
    }

    // F8: config.rs keeps an INDEPENDENT literal default; this proves it stays
    // in sync with the JSON SoT (non-tautological — different source).
    #[test]
    fn config_default_matches_registry() {
        let cfg = crate::backend::config::LlmConfig::default();
        assert_eq!(cfg.cloud_model, default_model("anthropic").unwrap());
    }
}
