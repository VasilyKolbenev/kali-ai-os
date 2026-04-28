//! SKILL.md parser — reads YAML frontmatter + Markdown body and
//! returns a structured [`SkillManifest`].
//!
//! Format (per <https://agentskills.io/specification>):
//!
//! ```text
//! ---
//! name: skill-name
//! description: What it does and when to use it.
//! license: MIT                   # optional
//! compatibility: ...             # optional
//! metadata:                       # optional, free-form mapping
//!   author: someone
//!   version: "1.0"
//! allowed-tools: Read Write Bash(git:*)   # optional, space-separated
//! ---
//!
//! # Skill body
//! ...
//! ```
//!
//! The Rust port mirrors `kernel/skills/loader.py::load_skill`. JSON
//! shape returned by `to_json` matches `SkillManifest.to_dict` so the
//! UI sees identical responses regardless of which backend serves
//! `/skills/installed`.

use std::path::{Path, PathBuf};

use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};

const FRONTMATTER_DELIM: &str = "---";

/// A parsed SKILL.md file. Field set mirrors Python's `SkillManifest`
/// dataclass — keep the JSON serialisation in `to_json` aligned with
/// `kernel/skills/loader.py::SkillManifest.to_dict`.
#[derive(Debug, Clone)]
pub struct SkillManifest {
    pub name: String,
    pub description: String,
    pub body: String,
    pub license: Option<String>,
    pub compatibility: Option<String>,
    pub metadata: Value,
    pub allowed_tools: Option<String>,
    pub skill_dir: PathBuf,
    pub has_scripts: bool,
    pub has_references: bool,
    pub has_assets: bool,
    pub source: String,
}

impl SkillManifest {
    /// Space-separated `allowed-tools` parsed into a list. Empty when
    /// the field is absent or only whitespace.
    pub fn tool_list(&self) -> Vec<String> {
        self.allowed_tools
            .as_deref()
            .map(|s| s.split_whitespace().map(String::from).collect())
            .unwrap_or_default()
    }

    /// JSON shape returned by the `/skills/installed` route. Mirrors
    /// `SkillManifest.to_dict` from the Python module byte-for-byte
    /// (modulo path string formatting on Windows).
    pub fn to_json(&self) -> Value {
        json!({
            "name": self.name,
            "description": self.description,
            "body": self.body,
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": self.metadata,
            "allowed_tools": self.allowed_tools,
            "allowed_tools_list": self.tool_list(),
            "skill_dir": self.skill_dir.to_string_lossy(),
            "has_scripts": self.has_scripts,
            "has_references": self.has_references,
            "has_assets": self.has_assets,
            "source": self.source,
        })
    }
}

/// Load and parse a SKILL.md from `skill_dir`. The file MUST exist;
/// callers are expected to have probed for it (`registry.rs` does).
/// `source` is propagated into the manifest as a provenance tag
/// (`"user"`, `"builtin"`, `"catalog:<id>"`, etc).
pub fn load_skill(skill_dir: &Path, source: &str) -> Result<SkillManifest> {
    let skill_md = skill_dir.join("SKILL.md");
    let content = std::fs::read_to_string(&skill_md)
        .with_context(|| format!("read SKILL.md at {:?}", skill_md))?;
    let (frontmatter, body) = split_frontmatter(&content)?;

    let dir_name = skill_dir
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();
    let name = frontmatter.name.unwrap_or(dir_name);
    let description = frontmatter.description.unwrap_or_default();
    let metadata = frontmatter
        .metadata
        .map(yaml_to_json)
        .transpose()?
        .unwrap_or_else(|| json!({}));

    Ok(SkillManifest {
        name,
        description,
        body,
        license: frontmatter.license,
        compatibility: frontmatter.compatibility,
        metadata,
        allowed_tools: frontmatter.allowed_tools,
        skill_dir: skill_dir.to_path_buf(),
        has_scripts: skill_dir.join("scripts").is_dir(),
        has_references: skill_dir.join("references").is_dir(),
        has_assets: skill_dir.join("assets").is_dir(),
        source: source.to_string(),
    })
}

/// Strict frontmatter shape used internally for the YAML deserialise
/// step. Optional everywhere — required-field validation is the
/// validator's job (Chunk 4); the loader is forgiving so a missing
/// `name` falls back to the directory name (matches Python).
#[derive(Debug, Default, Deserialize)]
pub(crate) struct Frontmatter {
    pub(crate) name: Option<String>,
    pub(crate) description: Option<String>,
    pub(crate) license: Option<String>,
    pub(crate) compatibility: Option<String>,
    pub(crate) metadata: Option<serde_yaml::Value>,
    #[serde(rename = "allowed-tools")]
    pub(crate) allowed_tools: Option<String>,
}

/// Convert the YAML `metadata` mapping into a JSON value so callers
/// can serialise it through serde_json without a double-walk. Errors
/// out only on inputs YAML accepts but JSON cannot represent (e.g.
/// non-string mapping keys). In practice metadata is always
/// `{string: scalar}` and this is a no-op cost-wise.
fn yaml_to_json(value: serde_yaml::Value) -> Result<Value> {
    serde_json::to_value(&value).context("convert YAML metadata to JSON")
}

/// Split file contents into (frontmatter, body). Mirrors the Python
/// `_split_frontmatter` semantics:
///   - Skip leading blank lines.
///   - First non-blank line MUST be `---`.
///   - Find the next `---` line; everything between is YAML.
///   - Body is everything after the closing delim, with leading
///     newlines trimmed.
pub(crate) fn split_frontmatter(content: &str) -> Result<(Frontmatter, String)> {
    let lines: Vec<&str> = content.lines().collect();
    if lines.is_empty() {
        return Err(anyhow!("SKILL.md is empty"));
    }

    let first_idx = lines
        .iter()
        .position(|l| !l.trim().is_empty())
        .ok_or_else(|| anyhow!("SKILL.md is empty"))?;

    if lines[first_idx].trim() != FRONTMATTER_DELIM {
        return Err(anyhow!(
            "SKILL.md must begin with YAML frontmatter delimited by '---'"
        ));
    }

    let end_idx = lines
        .iter()
        .enumerate()
        .skip(first_idx + 1)
        .find(|(_, l)| l.trim() == FRONTMATTER_DELIM)
        .map(|(i, _)| i)
        .ok_or_else(|| anyhow!("Unterminated frontmatter: missing closing '---'"))?;

    let frontmatter_text = lines[first_idx + 1..end_idx].join("\n");
    let body_text = lines[end_idx + 1..].join("\n");
    let body = body_text.trim_start_matches('\n').to_string();

    let parsed: Frontmatter = if frontmatter_text.trim().is_empty() {
        // Empty frontmatter is allowed in lenient mode — matches Python's
        // `data = yaml.safe_load(...) or {}`.
        Frontmatter::default()
    } else {
        serde_yaml::from_str(&frontmatter_text).context("Invalid YAML frontmatter")?
    };

    Ok((parsed, body))
}

/// Test helper: a frontmatter-only Manifest builder. Used by registry
/// integration tests to assemble a `SkillManifest` without touching the
/// filesystem.
#[cfg(test)]
#[allow(dead_code)]
pub(crate) fn manifest_for_test(name: &str, description: &str, source: &str) -> SkillManifest {
    SkillManifest {
        name: name.into(),
        description: description.into(),
        body: String::new(),
        license: None,
        compatibility: None,
        metadata: json!({}),
        allowed_tools: None,
        skill_dir: PathBuf::from("."),
        has_scripts: false,
        has_references: false,
        has_assets: false,
        source: source.into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_frontmatter_minimal() {
        let raw = "---\nname: x\ndescription: y\n---\n\nBody.\n";
        let (fm, body) = split_frontmatter(raw).unwrap();
        assert_eq!(fm.name.as_deref(), Some("x"));
        assert_eq!(fm.description.as_deref(), Some("y"));
        assert_eq!(body, "Body.");
    }

    #[test]
    fn split_frontmatter_skips_leading_blank_lines() {
        let raw = "\n\n---\nname: a\n---\nBody";
        let (fm, body) = split_frontmatter(raw).unwrap();
        assert_eq!(fm.name.as_deref(), Some("a"));
        assert_eq!(body, "Body");
    }

    #[test]
    fn split_frontmatter_rejects_missing_open_delim() {
        let raw = "name: x\ndescription: y\n";
        let err = split_frontmatter(raw).unwrap_err();
        assert!(err.to_string().contains("must begin with YAML frontmatter"));
    }

    #[test]
    fn split_frontmatter_rejects_unterminated() {
        let raw = "---\nname: x\ndescription: y\n";
        let err = split_frontmatter(raw).unwrap_err();
        assert!(err.to_string().contains("Unterminated frontmatter"));
    }

    #[test]
    fn split_frontmatter_empty_file_errors() {
        let err = split_frontmatter("").unwrap_err();
        assert!(err.to_string().contains("empty"));
    }

    #[test]
    fn tool_list_splits_on_whitespace_handling_complex_tokens() {
        let mut m = manifest_for_test("x", "y", "user");
        m.allowed_tools = Some("Read Write Bash(git:*)  Edit".into());
        assert_eq!(
            m.tool_list(),
            vec!["Read", "Write", "Bash(git:*)", "Edit"]
                .into_iter()
                .map(String::from)
                .collect::<Vec<_>>(),
        );
    }

    #[test]
    fn tool_list_empty_when_field_missing() {
        let m = manifest_for_test("x", "y", "user");
        assert!(m.tool_list().is_empty());
    }
}
