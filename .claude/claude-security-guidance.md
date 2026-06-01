# Security guidance — KALI AI OS

Project-specific review checklist for the security-guidance plugin. Applied
alongside the built-in vulnerability checklist on every model-backed review.
KALI is a voice-first AI agent platform for non-technical users: it holds user
LLM API keys, processes voice/personal data, generates and runs agent code in a
sandbox, and exposes a backend to mobile clients over LAN. Treat all of these as
trust boundaries.

## Secrets & credentials

- Never hardcode API keys, tokens, or passwords. User LLM keys (OpenAI,
  Anthropic, Gemini, DeepSeek, Groq, Mistral, ElevenLabs) live in `.env` /
  secure storage only — never in source, logs, or committed config.
- Flag any string matching `sk-`, `sk-proj-`, `AIza`, `AKIA`, or a 30+ char
  high-entropy literal assigned to a key/token/secret variable.
- Masked-key display (`_mask_key`) is the only acceptable way to surface a key
  value in API responses or the UI. Never return a raw key from `/settings`.

## Agent code generation & execution (high risk)

- `kernel/agent_builder.py` and `kernel/builder/*` generate Python agent code
  from user voice/text. Generated code runs in the sandbox — treat the
  generator output as untrusted.
- The `BLOCKED_PATTERNS` AST/regex gate in agent_builder must reject
  `subprocess`, `os.system`, `os.remove`, `shutil.rmtree`, `eval`, `exec`,
  `__import__`, and writes outside the skill data dir. Any change that weakens
  or bypasses this gate is a finding.
- Never `eval()` / `exec()` / `pickle.loads()` on user-derived input anywhere.
- Skill/agent file writes must stay inside the validated per-skill data dir
  (`SkillTemplate._validate_filename` blocks path traversal — `..`, `/`, `\`).
  Flag any file write that skips that validation.

## Network & backend exposure

- The backend binds `0.0.0.0` for mobile/LAN access (Rust broker :3006, Python
  :3005). Any new endpoint is reachable from the local network — it MUST
  validate and authorize input. No implicit "localhost-only" trust.
- Validate and sanitize all external input at the boundary (request bodies,
  WebSocket frames from mobile, agent tool args). Reject early with a clear
  error.
- Use HTTPS for outbound calls. Honor rate limiting on agent-facing endpoints.
- SSRF: agents that fetch URLs (web-surfer, monitor) must not be steerable to
  internal addresses (169.254.*, 127.*, 10.*, 192.168.*, metadata endpoints)
  without explicit allow.

## Frontend (Tauri/React) & DOM

- Never use `dangerouslySetInnerHTML`, `.innerHTML =`, or `document.write` with
  agent/LLM/user content. Canvas widgets (MarkdownWidget etc.) must render to
  safe React nodes — this regressed once and was fixed; do not reintroduce.
- Prototype pollution: do not index objects with untrusted keys via bracket
  notation without an `Object.prototype.hasOwnProperty.call` guard or a `Map`.
  This applies to AgentStore, ChatInput, and any registry keyed by agent/skill
  name.

## LLM API calls

- All provider calls must set `max_tokens` and pass user/metadata where the
  provider supports it; Gemini calls must set `safety_settings`. Wrap calls so a
  provider error never crashes the kernel or leaks the key in a stack trace.

## Data & SQL

- Use parameterized queries for all SQLite access (`aiosqlite` `?` placeholders).
  Never string-format user input into SQL. Long-term memory and intent-log
  tables store user-derived text — treat as untrusted on read-back too.
- Do not log `customer`/personal identifiers or full voice transcripts at INFO
  or above.

## VPN / obfuscation modules (if touched)

- Test that obfuscation does not leak identifiable patterns.
- Validate packet integrity after modification.

---

These are review guidance, not hard guardrails. The plugin surfaces violations
as findings for Claude to fix; it does not block writes. For hard enforcement,
pair with a PreToolUse hook or a CI check.
