export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export type WSMessage =
  | { type: "voice.state"; data: { state: VoiceState } }
  | { type: "voice.pipeline"; data: { active: boolean; mode: string } }
  | { type: "voice.transcript"; data: { text: string; final: boolean } }
  | { type: "agent.response"; data: { agent: string; text: string; data?: unknown } }
  | { type: "agent.status"; data: { agents: AgentStatus[] } }
  | { type: "agent.status.update"; data: { agent: string; status: string } }
  | { type: "dashboard.update"; data: { widget: string; data: unknown } }
  | { type: "error"; data: { source: string; message: string; code?: string } }
  | { type: "ui.command"; data: { command: string; args?: unknown } };

export interface AgentStatus {
  name: string;
  status: "running" | "stopped" | "error";
  health?: { status: string; uptime_s?: number };
}

export interface AgentManifest {
  name: string;
  version: string;
  description: string;
  capabilities: string[];
  protocol: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  components: {
    event_bus: { subscribers: number };
    database: { connected: boolean };
    scheduler: { morning_hour: number; evening_hour: number; is_running: boolean };
  };
}

export interface VoiceStatus {
  available: boolean;
  state: VoiceState;
  mode: string;
  ready?: boolean;
  started?: boolean;
  vad_loaded?: boolean;
  wake_word_loaded?: boolean;
  stt_loaded?: boolean;
  tts_loaded?: boolean;
  models_ready?: boolean;
  models_dir?: string;
  missing_models?: string[];
}

// --- Agent Skills (SKILL.md spec) ---
export interface CatalogSource {
  id: string;
  label: string;
  trust: "official" | "verified" | "community";
  owner: string;
  repo: string;
  ref: string;
  url: string;
}

export interface CatalogSkill {
  name: string;
  description: string;
  source_id: string;
  source_label: string;
  trust: "official" | "verified" | "community";
  repo_owner: string;
  repo_name: string;
  repo_ref: string;
  skill_path: string;
  license: string | null;
  compatibility: string | null;
  metadata: Record<string, unknown>;
  raw_skill_md_url: string;
  web_url: string;
}

export interface InstalledSkill {
  name: string;
  description: string;
  body: string;
  license: string | null;
  compatibility: string | null;
  metadata: Record<string, unknown>;
  allowed_tools: string | null;
  allowed_tools_list: string[];
  skill_dir: string;
  has_scripts: boolean;
  has_references: boolean;
  has_assets: boolean;
  source: string;
}

// --- Sandbox audit / activity ---
export type AuditStatus = "ok" | "denied" | "error";
export type DeniedReason = "rate_limit" | "permission" | "safety" | null;

export interface AuditRecord {
  id: number;
  timestamp: number;
  backend: string;
  agent: string;
  action: string;
  caller: string;
  status: AuditStatus;
  denied_reason: DeniedReason;
  duration_ms: number;
  request_id: string;
  error: string | null;
  extra: string | null;
}

export interface AuditAgentStats {
  agent: string;
  total: number;
  ok_count: number;
  denied_count: number;
  error_count: number;
  avg_ms: number | null;
}

export interface SandboxHealth {
  backend: string;
  enforcer_enabled: boolean;
  rate_limiter_enabled: boolean;
  audit_sink_enabled: boolean;
}
