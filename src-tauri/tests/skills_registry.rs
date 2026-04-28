//! Phase 4 Chunk 1 — local SKILL.md registry integration test.
//!
//! Builds a temp directory with two SKILL.md fixtures (one minimal,
//! one with optional fields), points a `SkillsRegistry` at it, and
//! verifies `list_all()` returns both manifests in name-sorted order
//! with the expected fields. No HTTP, no async, no engines — pure
//! filesystem I/O so it runs in the default suite.

use std::fs;
use std::path::PathBuf;

use kali_desktop::backend::skills::loader::SkillManifest;
use kali_desktop::backend::skills::registry::{SkillSource, SkillsRegistry};

fn write_skill(root: &std::path::Path, name: &str, body: &str) -> PathBuf {
    let dir = root.join(name);
    fs::create_dir_all(&dir).unwrap();
    let skill_md = dir.join("SKILL.md");
    fs::write(&skill_md, body).unwrap();
    dir
}

#[test]
fn registry_discovers_two_skills_from_a_source() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path();

    write_skill(
        root,
        "alpha",
        r#"---
name: alpha
description: First test skill.
---

# alpha

Body content for alpha.
"#,
    );
    write_skill(
        root,
        "beta",
        r#"---
name: beta
description: Second test skill.
license: MIT
allowed-tools: Read Write Bash(git:*)
metadata:
  author: vasily
  version: "1.0"
---

# beta

Body content for beta.
"#,
    );

    let registry = SkillsRegistry::new(vec![SkillSource {
        name: "user".into(),
        path: root.to_path_buf(),
        read_only: false,
    }]);
    registry.discover().expect("discover ok");

    let all = registry.list_all();
    assert_eq!(all.len(), 2, "expected exactly 2 skills");
    assert_eq!(all[0].name, "alpha", "list must be name-sorted");
    assert_eq!(all[1].name, "beta");

    // Optional-field round-trip on the richer fixture
    let beta: &SkillManifest = &all[1];
    assert_eq!(beta.description, "Second test skill.");
    assert_eq!(beta.license.as_deref(), Some("MIT"));
    assert_eq!(beta.allowed_tools.as_deref(), Some("Read Write Bash(git:*)"));
    assert_eq!(
        beta.tool_list(),
        vec!["Read".to_string(), "Write".into(), "Bash(git:*)".into()],
    );
    assert_eq!(beta.source, "user");
    assert!(
        beta.body.contains("Body content for beta"),
        "body must include markdown after the closing delimiter",
    );
}

#[test]
fn registry_user_source_overrides_builtin_on_name_collision() {
    let temp = tempfile::tempdir().expect("tempdir");
    let builtin_root = temp.path().join("builtin");
    let user_root = temp.path().join("user");
    fs::create_dir_all(&builtin_root).unwrap();
    fs::create_dir_all(&user_root).unwrap();

    write_skill(
        &builtin_root,
        "shared",
        r#"---
name: shared
description: Bundled version.
---

# shared (builtin)
"#,
    );
    write_skill(
        &user_root,
        "shared",
        r#"---
name: shared
description: User-customised version.
---

# shared (user)
"#,
    );

    // User listed first = highest priority. Registry processes in
    // reverse so user wins on collision.
    let registry = SkillsRegistry::new(vec![
        SkillSource {
            name: "user".into(),
            path: user_root,
            read_only: false,
        },
        SkillSource {
            name: "builtin".into(),
            path: builtin_root,
            read_only: true,
        },
    ]);
    registry.discover().expect("discover ok");

    let resolved = registry.get("shared").expect("must find collided skill");
    assert_eq!(
        resolved.description, "User-customised version.",
        "user source must override builtin on name collision",
    );
    assert_eq!(resolved.source, "user");
}

#[test]
fn registry_skips_malformed_skill_without_failing_others() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path();

    // Good skill
    write_skill(
        root,
        "ok",
        r#"---
name: ok
description: Valid.
---

Body.
"#,
    );
    // Malformed: missing closing delimiter
    write_skill(
        root,
        "broken",
        r#"---
name: broken
description: Missing closing delimiter
"#,
    );

    let registry = SkillsRegistry::new(vec![SkillSource {
        name: "user".into(),
        path: root.to_path_buf(),
        read_only: false,
    }]);
    registry.discover().expect("discover ok despite one malformed entry");

    let names: Vec<String> = registry
        .list_all()
        .into_iter()
        .map(|m| m.name)
        .collect();
    assert_eq!(names, vec!["ok"], "broken skill must be skipped, not crash");
}
