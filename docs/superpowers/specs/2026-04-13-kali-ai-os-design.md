# KALI AI OS — Skills, Agents & Marketplace Design

> **Spec for:** AI OS layer — Skills engine, AgentBuilder v2, Sandbox, Cloud Catalog
> **Date:** 2026-04-13
> **Status:** Approved by user, ready for implementation planning
> **Depends on:** Core Kernel (done), Agent Runtime (done), Voice Pipeline (done), TTS (done)

---

## 1. Overview

KALI AI OS adds three capabilities on top of the existing kernel:

1. **Skills** — lightweight YAML-configured automations from built-in templates
2. **AgentBuilder v2** — LLM-powered code generation for full agents, driven by voice
3. **Cloud Catalog** — marketplace for sharing and discovering Skills & Agents

The user interacts with all three through a unified Voice Wizard. They say what they want; the system decides whether to create a Skill or Agent, builds it, and deploys it.

---

## 2. Skills Engine

### 2.1 What is a Skill?

A Skill is a YAML config file that parameterizes a built-in template. No user code. No sandbox needed. The kernel executes the template with the user's parameters.

### 2.2 Built-in Templates

| Template | Purpose | Trigger | Output |
|----------|---------|---------|--------|
| **tracker** | Track a numeric value over time | Voice command / schedule | Daily summary, trends, charts |
| **monitor** | Check a URL/API periodically | Cron schedule | Alert on condition |
| **notifier** | Send notification on trigger | Event bus topic | Telegram / voice / push |
| **reminder** | Time-based reminders | Cron / interval | Voice / notification |
| **logger** | Record events with notes | Voice command | History, search |

### 2.3 Skill File Structure

```
agents/{skill-name}/
├── manifest.yaml    # standard agent manifest (protocol: skill)
└── skill.yaml       # template config
```

**manifest.yaml:**
```yaml
name: water-tracker
version: "1.0.0"
description: "Tracks daily water intake with reminders"
protocol: skill
capabilities: [tracker]
tools:
  - name: log
    description: "Log water intake"
    parameters:
      amount: {type: number, description: "Amount in ml"}
  - name: summary
    description: "Get daily summary"
    parameters: {}
scheduled_events: []
permissions: [storage, notifications]
```

**skill.yaml:**
```yaml
template: tracker
display_name: "Трекер воды"
config:
  unit: "мл"
  daily_goal: 2000
  reminders:
    enabled: true
    interval_hours: 2
    start_hour: 8
    end_hour: 22
    message: "Время выпить воды!"
  tracking:
    daily_summary: true
    weekly_chart: true
```

### 2.4 Skill Runtime

Skills don't spawn a subprocess. The kernel's **SkillExecutor** reads `skill.yaml`, loads the matching template class, and handles tool calls directly in-process.

```python
class SkillExecutor:
    """Executes Skills in-process using template classes."""

    templates: dict[str, type[SkillTemplate]]  # tracker, monitor, etc.

    async def execute(self, skill_name: str, action: str, args: dict) -> dict:
        """Load skill config, delegate to template."""

class SkillTemplate(ABC):
    """Base class for Skill templates."""

    @abstractmethod
    async def execute(self, action: str, args: dict, config: dict) -> dict: ...
```

Templates are part of the kernel — trusted code, not user-generated.

### 2.5 Skill Scheduling

The existing Scheduler emits only 3 fixed events. Skills need dynamic scheduling. Extend Scheduler with:

```python
class Scheduler:
    async def register_cron(self, name: str, cron: str, topic: str) -> None:
        """Register dynamic cron job. E.g., '0 */2 * * *' for every 2 hours."""

    async def register_interval(self, name: str, seconds: int, topic: str) -> None:
        """Register interval-based trigger."""

    async def unregister(self, name: str) -> None:
        """Remove dynamic schedule."""
```

When a Skill is deployed, SkillExecutor reads `config.reminders.interval_hours` or `config.schedule.cron` and registers with Scheduler. Scheduler emits `skill.{name}.trigger` → SkillExecutor handles it.

### 2.6 Skill Data Storage

Skills store data at `data/skills/{name}/` (separate from agents). SkillExecutor provides storage API to templates:

```python
class SkillTemplate(ABC):
    async def load_data(self, filename: str) -> Any: ...
    async def save_data(self, filename: str, data: Any) -> None: ...
```

### 2.7 Protocol Registration

Add `"skill"` to valid protocols in `AgentManifest`. PluginRegistry discovers Skills alongside Agents but routes them to SkillExecutor instead of AgentRuntime. AgentRuntime ignores `protocol: skill` entries.

---

## 3. AgentBuilder v2

### 3.1 Components

| Component | Input | Output |
|-----------|-------|--------|
| **Intent Classifier** | User's voice request | Skill (template match) or Agent (needs code) |
| **Voice Wizard** | Intent | 2-4 clarifying questions → structured spec |
| **Skill Generator** | Spec | `skill.yaml` + `manifest.yaml` |
| **Agent Generator** | Spec | `agent.py` + `manifest.yaml` (via Claude LLM) |
| **Safety Gate** | Generated code | Pass / Fail + permission list |
| **Deployer** | Verified files | Installed & running agent |

### 3.2 Intent Classifier Logic

```
Input: user request text
Output: { type: "skill" | "agent", template?: string, reason: string }

Rules:
- If request matches a template pattern → Skill
  - "track/monitor X" → tracker
  - "remind me / напоминай" → reminder  
  - "notify when / уведоми когда" → notifier
  - "check X every Y" → monitor
  - "log / записывай" → logger
- If request needs external API → Agent
- If request needs custom logic → Agent
- If request needs other agents → Agent
- Ambiguous → ask user via Voice Wizard
```

### 3.3 Voice Wizard Protocol

The wizard is a structured conversation over TTS/STT. Maximum 4 questions.

```python
class WizardSession:
    """Guided voice conversation to spec out a Skill or Agent."""

    request: str           # original user request
    intent: IntentResult   # skill or agent
    questions: list[str]   # questions to ask
    answers: dict          # user answers
    spec: dict             # final structured spec

    async def next_question(self) -> str | None:
        """Return next question or None if done."""

    async def process_answer(self, answer: str) -> None:
        """Process user's voice answer, maybe add follow-up."""

    async def build_spec(self) -> dict:
        """Compile answers into structured spec for generator."""
```

**Standard questions by intent:**

For Skills:
1. "Как часто?" (interval/schedule)
2. "Какая цель?" (target value, if tracker)
3. "Куда уведомлять?" (voice/telegram/dashboard)

For Agents:
1. "Что конкретно делать?" (refine scope)
2. "Какие данные нужны?" (APIs, sources)
3. "Как часто и куда результат?" (schedule + output)
4. "Нужен доступ к [X]?" (permissions confirmation)

### 3.4 Agent Code Generation

Claude API generates `agent.py` from a structured prompt:

**System prompt (condensed):**
```
You are KALI AgentBuilder. Generate a Python agent inheriting BaseAgent.

Requirements:
- Implement get_name() and handle_action()
- Use self._load_json() / self._save_json() for data
- Only stdlib + requests for HTTP (no pip installs)
- Never use eval(), exec(), subprocess, os.system(), __import__()
- All external calls wrapped in try/except
- Return dict from every action
- Type hints on all functions

Output format:
1. agent.py — full implementation
2. manifest.yaml — tools, permissions, capabilities
```

**User prompt:**
```
Create agent: {spec.name}
Description: {spec.description}
Tools: {spec.tools}
Schedule: {spec.schedule}
External APIs: {spec.apis}
Notifications: {spec.notifications}
```

### 3.5 Safety Gate

Three checks before any generated code runs:

**1. Static Analysis (true AST walking, not string matching):**

```python
import ast

BLOCKED_IMPORTS = {"subprocess", "importlib", "ctypes", "multiprocessing"}
BLOCKED_ATTRIBUTES = {"os.system", "os.popen", "os.remove", "os.rmdir",
                      "shutil.rmtree", "builtins.eval", "builtins.exec"}
BLOCKED_CALLS = {"eval", "exec", "__import__", "compile", "getattr", "globals"}

class SafetyVisitor(ast.NodeVisitor):
    """Walk AST nodes, reject dangerous patterns."""

    def visit_Import(self, node): ...      # block BLOCKED_IMPORTS
    def visit_ImportFrom(self, node): ...  # block BLOCKED_IMPORTS
    def visit_Call(self, node): ...        # block BLOCKED_CALLS + attribute chains
    def visit_Attribute(self, node): ...   # block BLOCKED_ATTRIBUTES
```

True AST analysis prevents bypasses via `getattr()`, string concatenation, `globals()`, and attribute chains. String-matching is NOT sufficient.

**2. LLM Review:**
Send generated code to Claude with prompt: "Review this agent code for security issues. Is it safe to run in a sandbox with these permissions: {permissions}? Reply SAFE or UNSAFE with reason."

**3. Permission Extraction:**
Parse manifest.yaml, extract all permissions, compare with what the wizard collected. Flag any unexpected permissions.

### 3.6 Deployer

```python
async def deploy(self, name: str, files: dict[str, str]) -> None:
    """Deploy generated agent/skill to the system."""
    # 1. Write files to agents/{name}/
    # 2. Register in PluginRegistry
    # 3. Load via AgentRuntime
    # 4. Run health check
    # 5. Announce via event bus: agent.installed
```

### 3.7 Error Handling & Rollback

**Safety Gate rejection:**
- LLM regenerates with modified prompt (max 2 retries)
- If still fails → Jarvis: "Не удалось создать безопасного агента. Попробуйте упростить запрос."
- No files written to disk until Safety Gate passes

**Deployment failure (health check):**
- Written files cleaned up from `agents/{name}/`
- Agent unregistered from PluginRegistry
- Jarvis: "Агент не прошёл проверку. Попробовать снова?"

**User declines permissions:**
- No files written, session discarded
- Jarvis: "Понял, отменяю."

**LLM API unavailable:**
- Safety Gate LLM review is advisory, not hard gate — fail-closed (block deploy)
- Agent generation requires Claude API — fail with clear message
- Skills don't need LLM — always work offline

### 3.8 Voice Wizard Lifecycle

- **Timeout:** 30 seconds of silence → "Хотите продолжить создание агента?"
- **Cancel:** user says "отмена" / "стоп" → session discarded
- **Concurrent:** only one wizard session at a time
- **Integration:** wizard uses existing voice pipeline STT/TTS, kernel routes via event bus topic `builder.wizard`

### 3.9 Voice-Driven Iteration

Existing agents/skills can be modified by voice:

```
"Jarvis, измени трекер воды — добавь учёт кофе"
```

Flow:
1. Load existing skill.yaml or agent.py
2. LLM generates diff based on request
3. Safety Gate checks modified code
4. Hot-reload agent

---

## 4. Sandbox & Permissions

### 4.1 Permission Types

| Permission | What it grants | Risk level |
|-----------|----------------|------------|
| `storage` | Read/write `data/agents/{name}/` | Low |
| `notifications` | Send voice/push/dashboard alerts | Low |
| `event_bus` | Subscribe to kernel events | Medium |
| `network` | HTTP to whitelisted domains | Medium |
| `agents` | Call other agents' tools | Medium |
| `system` | Read system info (time, platform) | Low |

### 4.2 Network Proxy via JSON-RPC

Subprocess agents cannot make HTTP calls directly (no `requests` import allowed — blocked by Safety Gate). Instead, network access goes through JSON-RPC:

**Agent side** — calls kernel via stdin/stdout:
```python
# In BaseAgent, provided to all agents:
def http_request(self, method: str, url: str, **kwargs) -> dict:
    """Send HTTP request through kernel proxy."""
    return self._rpc_call("network.request", {
        "method": method, "url": url, **kwargs
    })
```

**Kernel side** — NetworkProxy handles JSON-RPC method `network.request`:
```python
class NetworkProxy:
    """Handles 'network.request' JSON-RPC calls from agents."""

    async def handle(self, agent_name: str, params: dict) -> dict:
        domain = extract_domain(params["url"])
        if domain not in self._allowed_domains[agent_name]:
            return {"error": f"Blocked: {domain} not in whitelist"}
        if self._rate_limiter.exceeded(agent_name):
            return {"error": "Rate limit exceeded"}
        response = await self._client.request(
            params["method"], params["url"],
            headers=params.get("headers"),
            json=params.get("json"),
        )
        return {"status": response.status_code, "body": response.text}
```

**Rate limiting:** Per-agent limits (default 60 req/min) prevent abuse of allowed domains.

This approach is secure because:
- Agents never import `requests` or `urllib` (blocked by Safety Gate)
- All network traffic flows through kernel where it can be logged, throttled, blocked
- No local proxy server needed — uses existing JSON-RPC channel

### 4.3 Filesystem Sandbox

Agents access files only through BaseAgent's `_load_json()` / `_save_json()` which enforce path within `data/agents/{name}/`. Direct `open()` calls are blocked by Safety Gate.

### 4.4 Approval Flow

```
AgentBuilder generates code + manifest
    → Safety Gate: static + LLM review
    → Permission Analyzer extracts required permissions
    → Jarvis speaks: "Agent needs: network (api.example.com), telegram. Allow?"
    → User confirms by voice
    → Permissions stored in agent_configs DB
    → Agent deployed and running
```

---

## 5. Cloud Catalog

### 5.1 Backend (Supabase)

**Tables:**
```sql
packages (
    id uuid PRIMARY KEY,
    name text UNIQUE,
    display_name text,
    description text,
    type text,           -- 'skill' | 'agent'
    category text,       -- 'health', 'finance', 'productivity', ...
    author_id uuid REFERENCES authors,
    version text,
    trust_level text,    -- 'official', 'verified', 'community'
    permissions jsonb,
    downloads integer DEFAULT 0,
    rating_avg float DEFAULT 0,
    created_at timestamptz,
    updated_at timestamptz
)

authors (
    id uuid PRIMARY KEY,
    username text UNIQUE,
    display_name text,
    kali_user_id uuid,   -- linked to KALI desktop auth
    verified boolean DEFAULT false,
    created_at timestamptz
)

reviews (
    id uuid PRIMARY KEY,
    package_id uuid REFERENCES packages,
    author_id uuid REFERENCES authors,
    rating integer CHECK (rating BETWEEN 1 AND 5),
    comment text,
    created_at timestamptz
)

package_files (
    id uuid PRIMARY KEY,
    package_id uuid REFERENCES packages,
    file_path text,
    content_hash text,
    storage_path text,    -- Supabase Storage path
    created_at timestamptz
)
```

### 5.2 Package Format

`.kali-agent` is a zip file:
```
{name}.kali-agent
├── manifest.yaml         # agent metadata + permissions
├── agent.py              # code (Agents only)
├── skill.yaml            # template config (Skills only)
├── icon.png              # 256x256 icon
├── README.md             # description for catalog
└── checksum.sha256       # integrity verification
```

### 5.3 API Endpoints

```
GET    /api/catalog/search?q=water&category=health
GET    /api/catalog/packages/{name}
GET    /api/catalog/packages/{name}/reviews
POST   /api/catalog/packages              # publish
PUT    /api/catalog/packages/{name}       # update
DELETE /api/catalog/packages/{name}       # unpublish
POST   /api/catalog/packages/{name}/reviews
GET    /api/catalog/trending
GET    /api/catalog/categories
```

### 5.4 Install Flow

```
1. User: "Jarvis, найди агента для бюджета"
2. Kernel → Catalog API: search("бюджет", category="finance")
3. Jarvis voices top 3 results with ratings
4. User: "Установи первый"
5. Kernel downloads .kali-agent
6. Verify checksum
7. Extract + Safety Gate (for agents with code)
8. Permission approval (voice)
9. Deploy to agents/{name}/
10. Jarvis: "Агент Budget Pro установлен и готов к работе"
```

### 5.5 Publish Flow

```
1. User: "Jarvis, опубликуй мой трекер воды"
2. AgentBuilder packages files into .kali-agent
3. Jarvis: "Описание: трекер воды с напоминаниями. Категория: здоровье. Опубликовать?"
4. User confirms
5. Upload to Supabase Storage
6. Create catalog entry (trust_level: community)
7. Jarvis: "Опубликовано! Другие пользователи могут его найти в магазине"
```

---

## 6. Implementation Priority

This spec decomposes into four chunks. Order matters — sandbox MUST exist before generated code runs.

### Chunk 1: Skill Engine
- Add `"skill"` to AgentManifest protocol validator
- SkillTemplate base class + 5 templates (tracker, monitor, notifier, reminder, logger)
- SkillExecutor (kernel in-process runner with storage API)
- Extend Scheduler with dynamic cron/interval registration
- Skill discovery in PluginRegistry (route to SkillExecutor, not AgentRuntime)
- Voice creation of Skills via existing AgentBuilder

### Chunk 2: Sandbox & Permissions
- Structured permission model in AgentManifest (replace flat `list[str]`)
- NetworkProxy via JSON-RPC `network.request` method
- Per-agent rate limiting (60 req/min default)
- Filesystem enforcement (path validation in BaseAgent)
- Permission Approval flow (voice + UI confirmation)
- Runtime enforcement in AgentRuntime protocol layer

### Chunk 3: AgentBuilder v2
- Intent Classifier (skill vs agent)
- Voice Wizard (structured conversation with timeout/cancel)
- LLM Agent Generator (Claude API with structured prompt)
- Safety Gate (true AST analysis + LLM advisory review)
- Error handling & rollback (retry, cleanup, user feedback)
- Deployer (write + register + load + health check)
- Voice iteration (modify existing agents/skills)

### Chunk 4: Cloud Catalog
- Supabase schema + auth (anonymous browse, authenticated publish)
- Package format (.kali-agent) with server-side checksum verification
- Publish flow (package + safety scan + upload)
- Install flow (download + verify + Safety Gate + permission approval)
- Search + browse UI in desktop app
- Ratings, reviews, abuse reporting
- Trust levels (official/verified/community)

### Dependencies
```
Chunk 1 (Skills) ← independent, start first
Chunk 2 (Sandbox) ← independent, can parallel with Chunk 1
Chunk 3 (Builder v2) ← needs Chunk 1 (skill gen) + Chunk 2 (sandbox for agents)
Chunk 4 (Catalog) ← needs Chunks 1-3 for full flow
```

### Prerequisite work (before chunks)
- Extend Scheduler for dynamic cron registration
- Add `"skill"` protocol to AgentManifest model
- Robust Claude API wrapper with retries/error handling in LLM Router
- Migrate AgentBuilder v1 code → v2 (replace regex safety with AST)

---

## 7. Security Considerations

- **AST analysis, not string matching** — Safety Gate must walk `ast.NodeVisitor` to catch `getattr()`, `globals()`, and attribute chain bypasses
- **Network proxy via JSON-RPC** — agents never import `requests`/`urllib`, all HTTP goes through kernel
- **Rate limiting** — per-agent request limits prevent API abuse
- **Community packages** — auto-scanned but run in full sandbox with runtime enforcement; consider restricted OS-level user for extra isolation in v2
- **Content moderation** — Cloud Catalog needs abuse reporting and takedown mechanism
- **Permission approval** — voice confirmation backed by UI visual indicator to prevent audio injection attacks
- **LLM review is advisory** — fail-closed (block deploy) when unavailable, not fail-open
- **Package integrity** — server-side checksum verification (not in-package); author signatures in v2

---

## 8. What's NOT in Scope

- Mobile app (v3)
- Hardware device / Raspberry Pi (v3+)
- Multi-user / enterprise features
- Paid marketplace / monetization
- Agent-to-agent orchestration (v2.5)
- Custom voice training UI (v2.5)

---

*Spec version: 1.0*
*Date: 2026-04-13*
*Author: Vasily + Claude*
