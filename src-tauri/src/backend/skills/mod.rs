//! Skills subsystem — local registry, remote catalog, installer, validator.
//!
//! Phase 4 ports `kernel/skills/{loader,registry,catalog,installer,validator}.py`
//! to Rust. Chunk 1 introduces the local SKILL.md registry; subsequent
//! chunks layer on the remote catalog client (Chunk 2), installer
//! (Chunk 3), validator (Chunk 4), and the legacy `.kali-agent`
//! package format (Chunk 5).
//!
//! Skill *execution* (`POST /skills/{name}/{action}`) stays in Python
//! — skills are Python code, the runtime owns them. Same precedent as
//! STT and wake-word path B in Phase 3.

pub mod loader;
pub mod registry;
