//! SKILL.md spec validator. Mirrors `kernel/skills/{validator,publisher}.py`
//! — implements the Agent Skills v1 frontmatter rules plus
//! publish-time advisory warnings, returning a single
//! [`ValidationResult`] consumed by `POST /skills/validate`.
//!
//! ## Rule set (per <https://agentskills.io/specification>)
//!
//! Required:
//! - `name` — 1-64 chars; lowercase letters, digits, hyphens; no
//!   leading/trailing/consecutive hyphens. Single-char names are OK.
//! - `description` — 1-1024 chars, non-empty after trimming.
//!
//! Optional (only validated if present):
//! - `license`, `allowed-tools` — must be strings (type-enforced by
//!   serde during loader parse, so a Rust caller will never see a
//!   non-string value here).
//! - `compatibility` — string, ≤ 500 chars.
//! - `metadata` — mapping of string keys to scalar values (string,
//!   int, float, bool). Nested mappings/sequences emit warnings.
//!
//! Cross-field:
//! - When invoked with an `expected_name` (= the parent directory
//!   name), `name` must match exactly.
//!
//! Publish-time warnings (non-fatal):
//! - description < 40 chars (poor LLM discovery).
//! - missing `license`.
//! - SKILL.md body < 50 chars (lacks instructions for the agent).

use std::path::Path;

use serde::Serialize;
use serde_json::Value;

use crate::backend::skills::loader::{load_skill, SkillManifest};

const NAME_MAX_LEN: usize = 64;
const DESCRIPTION_MAX_LEN: usize = 1024;
const COMPATIBILITY_MAX_LEN: usize = 500;
const SHORT_DESCRIPTION_THRESHOLD: usize = 40;
const SHORT_BODY_THRESHOLD: usize = 50;

/// Final outcome of a validation pass. Mirrors Python's
/// `ValidationResult` dataclass shape.
#[derive(Debug, Clone, Serialize)]
pub struct ValidationResult {
    pub valid: bool,
    pub errors: Vec<String>,
    pub warnings: Vec<String>,
}

/// Validate a skill directory against the spec + publish-time
/// advisories. Errors are fatal (caller should refuse install /
/// publish); warnings are advisory (UI can surface them).
///
/// Equivalent to `kernel.skills.publisher.validate_skill` — runs
/// `validator.validate_frontmatter` plus the three publish-extra
/// warnings the publisher module appends.
pub fn validate_skill(skill_dir: &Path) -> ValidationResult {
    let mut errors: Vec<String> = Vec::new();
    let mut warnings: Vec<String> = Vec::new();

    if !skill_dir.is_dir() {
        errors.push(format!(
            "Skill directory not found: {}",
            skill_dir.display()
        ));
        return ValidationResult {
            valid: false,
            errors,
            warnings,
        };
    }

    let skill_md = skill_dir.join("SKILL.md");
    if !skill_md.is_file() {
        errors.push(format!("SKILL.md missing in {}", skill_dir.display()));
        return ValidationResult {
            valid: false,
            errors,
            warnings,
        };
    }

    let manifest = match load_skill(skill_dir, "local") {
        Ok(m) => m,
        Err(err) => {
            errors.push(format!("Failed to parse SKILL.md: {err}"));
            return ValidationResult {
                valid: false,
                errors,
                warnings,
            };
        }
    };

    let expected_name = skill_dir.file_name().and_then(|n| n.to_str());
    validate_manifest(&manifest, expected_name, &mut errors, &mut warnings);

    ValidationResult {
        valid: errors.is_empty(),
        errors,
        warnings,
    }
}

/// Validate a parsed manifest in-memory. Public so callers that
/// already hold a manifest (e.g. the registry) can validate without
/// re-reading from disk.
pub fn validate_manifest(
    manifest: &SkillManifest,
    expected_name: Option<&str>,
    errors: &mut Vec<String>,
    warnings: &mut Vec<String>,
) {
    validate_name(&manifest.name, errors);
    validate_description(&manifest.description, errors);

    if let Some(compat) = manifest.compatibility.as_deref() {
        validate_compatibility(compat, errors);
    }
    // license, allowed_tools — types are enforced by serde at load
    // time; a non-string would have failed parsing. Nothing further
    // to check beyond presence (which is optional).

    validate_metadata(&manifest.metadata, errors, warnings);

    if let Some(expected) = expected_name {
        if manifest.name != expected {
            errors.push(format!(
                "name '{}' does not match parent directory '{}'",
                manifest.name, expected
            ));
        }
    }

    // Publish-time advisory warnings.
    if manifest.description.len() < SHORT_DESCRIPTION_THRESHOLD {
        warnings.push(
            "description is very short — add keywords describing when to use the skill for better LLM discovery".into(),
        );
    }
    if manifest.license.is_none() {
        warnings.push(
            "no license specified — publishers should add a license (MIT/Apache-2.0 recommended)".into(),
        );
    }
    if manifest.body.trim().len() < SHORT_BODY_THRESHOLD {
        warnings
            .push("SKILL.md body is very short — add instructions + examples for agents".into());
    }
}

fn validate_name(name: &str, errors: &mut Vec<String>) {
    if name.is_empty() {
        errors.push("name is required and must not be empty".into());
        return;
    }
    if name.len() > NAME_MAX_LEN {
        errors.push(format!(
            "name exceeds {NAME_MAX_LEN} characters ({})",
            name.len()
        ));
    }
    if name.starts_with('-') {
        errors.push("name must not start with a hyphen".into());
    }
    if name.ends_with('-') {
        errors.push("name must not end with a hyphen".into());
    }
    if name.contains("--") {
        errors.push("name must not contain consecutive hyphens".into());
    }
    if !name
        .chars()
        .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
    {
        errors
            .push("name must contain only lowercase letters, digits, and hyphens".into());
    }
}

fn validate_description(description: &str, errors: &mut Vec<String>) {
    if description.trim().is_empty() {
        errors.push("description is required and must not be empty".into());
        return;
    }
    if description.len() > DESCRIPTION_MAX_LEN {
        errors.push(format!(
            "description exceeds {DESCRIPTION_MAX_LEN} characters ({})",
            description.len()
        ));
    }
}

fn validate_compatibility(value: &str, errors: &mut Vec<String>) {
    if value.len() > COMPATIBILITY_MAX_LEN {
        errors.push(format!(
            "compatibility exceeds {COMPATIBILITY_MAX_LEN} characters ({})",
            value.len()
        ));
    }
}

/// Metadata must be a mapping of string keys to scalar values.
/// Mirrors Python's `_validate_metadata` — disallows nested
/// mappings or sequences. Empty/null metadata is OK.
fn validate_metadata(value: &Value, errors: &mut Vec<String>, _warnings: &mut Vec<String>) {
    match value {
        Value::Null => {}
        Value::Object(map) => {
            for (k, v) in map.iter() {
                let scalar_ok = matches!(
                    v,
                    Value::String(_) | Value::Number(_) | Value::Bool(_) | Value::Null
                );
                if !scalar_ok {
                    let kind = match v {
                        Value::Array(_) => "array",
                        Value::Object(_) => "object",
                        _ => "non-scalar",
                    };
                    errors.push(format!(
                        "metadata['{k}'] must be a scalar value, got {kind}"
                    ));
                }
                let _ = k;
            }
        }
        other => {
            errors.push(format!(
                "metadata must be a mapping, got {}",
                json_type_name(other)
            ));
        }
    }
}

fn json_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "null",
        Value::Bool(_) => "boolean",
        Value::Number(_) => "number",
        Value::String(_) => "string",
        Value::Array(_) => "array",
        Value::Object(_) => "object",
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backend::skills::loader::manifest_for_test;
    use serde_json::json;

    fn validate(manifest: &SkillManifest, expected: Option<&str>) -> ValidationResult {
        let mut errors = Vec::new();
        let mut warnings = Vec::new();
        validate_manifest(manifest, expected, &mut errors, &mut warnings);
        ValidationResult {
            valid: errors.is_empty(),
            errors,
            warnings,
        }
    }

    fn good_manifest(name: &str) -> SkillManifest {
        let mut m = manifest_for_test(
            name,
            "A skill description that is long enough to satisfy the publish warning threshold by some margin.",
            "user",
        );
        m.body = "Body text long enough to clear the publish-time short-body warning easily.".into();
        m.license = Some("MIT".into());
        m
    }

    #[test]
    fn good_skill_validates_clean() {
        let m = good_manifest("weather");
        let r = validate(&m, Some("weather"));
        assert!(r.valid, "expected clean: {:?}", r.errors);
        assert!(r.errors.is_empty());
        assert!(r.warnings.is_empty());
    }

    #[test]
    fn empty_name_errors() {
        let mut m = good_manifest("ok");
        m.name = String::new();
        let r = validate(&m, None);
        assert!(!r.valid);
        assert!(r.errors.iter().any(|e| e.contains("name is required")));
    }

    #[test]
    fn too_long_name_errors() {
        let mut m = good_manifest("ok");
        m.name = "a".repeat(NAME_MAX_LEN + 1);
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("exceeds 64")));
    }

    #[test]
    fn name_with_uppercase_errors() {
        let mut m = good_manifest("ok");
        m.name = "Bad-Name".into();
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("only lowercase")));
    }

    #[test]
    fn name_with_consecutive_hyphens_errors() {
        let mut m = good_manifest("ok");
        m.name = "weather--api".into();
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("consecutive hyphens")));
    }

    #[test]
    fn name_with_leading_or_trailing_hyphen_errors() {
        let mut m = good_manifest("ok");
        m.name = "-leading".into();
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("not start with a hyphen")));

        let mut m = good_manifest("ok");
        m.name = "trailing-".into();
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("not end with a hyphen")));
    }

    #[test]
    fn empty_description_errors() {
        let mut m = good_manifest("ok");
        m.description = String::new();
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("description is required")));
    }

    #[test]
    fn too_long_description_errors() {
        let mut m = good_manifest("ok");
        m.description = "x".repeat(DESCRIPTION_MAX_LEN + 1);
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("exceeds 1024")));
    }

    #[test]
    fn short_description_warns_but_does_not_fail() {
        let mut m = good_manifest("ok");
        m.description = "short".into();
        let r = validate(&m, None);
        assert!(r.valid);
        assert!(r.warnings.iter().any(|w| w.contains("description is very short")));
    }

    #[test]
    fn missing_license_warns() {
        let mut m = good_manifest("ok");
        m.license = None;
        let r = validate(&m, None);
        assert!(r.valid);
        assert!(r.warnings.iter().any(|w| w.contains("no license specified")));
    }

    #[test]
    fn short_body_warns() {
        let mut m = good_manifest("ok");
        m.body = "x".into();
        let r = validate(&m, None);
        assert!(r.valid);
        assert!(r.warnings.iter().any(|w| w.contains("body is very short")));
    }

    #[test]
    fn name_mismatch_with_directory_errors() {
        let m = good_manifest("a");
        let r = validate(&m, Some("b"));
        assert!(r
            .errors
            .iter()
            .any(|e| e.contains("does not match parent directory")));
    }

    #[test]
    fn compatibility_too_long_errors() {
        let mut m = good_manifest("ok");
        m.compatibility = Some("x".repeat(COMPATIBILITY_MAX_LEN + 1));
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("compatibility exceeds")));
    }

    #[test]
    fn metadata_with_nested_object_errors() {
        let mut m = good_manifest("ok");
        m.metadata = json!({ "author": { "nested": "value" } });
        let r = validate(&m, None);
        assert!(r
            .errors
            .iter()
            .any(|e| e.contains("metadata['author']") && e.contains("scalar")));
    }

    #[test]
    fn metadata_with_array_errors() {
        let mut m = good_manifest("ok");
        m.metadata = json!({ "tags": ["a", "b"] });
        let r = validate(&m, None);
        assert!(r
            .errors
            .iter()
            .any(|e| e.contains("metadata['tags']") && e.contains("array")));
    }

    #[test]
    fn metadata_scalar_values_pass() {
        let mut m = good_manifest("ok");
        m.metadata = json!({
            "author": "vasily",
            "version": 1.0,
            "stable": true,
            "count": 42,
        });
        let r = validate(&m, None);
        assert!(r.valid, "scalar metadata should validate: {:?}", r.errors);
    }

    #[test]
    fn metadata_top_level_array_errors() {
        let mut m = good_manifest("ok");
        m.metadata = json!(["not", "a", "mapping"]);
        let r = validate(&m, None);
        assert!(r.errors.iter().any(|e| e.contains("metadata must be a mapping")));
    }
}
