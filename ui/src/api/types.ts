export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export type WSMessage =
  | { type: "voice.state"; data: { state: VoiceState } }
  | { type: "voice.pipeline"; data: { active: boolean; mode: string } }
  | { type: "voice.transcript"; data: { text: string; final: boolean } }
  | { type: "agent.response"; data: { agent: string; text: string; data?: unknown } }
  | { type: "agent.status"; data: { agents: AgentStatus[] } }
  | { type: "agent.status.update"; data: { agent: string; status: string } }
  | { type: "dashboard.update"; data: { widget: string; data: unknown } }
  | { type: "canvas.update"; data: { action: string; widget?: CanvasWidget; [key: string]: unknown } }
  | { type: "error"; data: { source: string; message: string; code?: string } }
  | { type: "ui.command"; data: { command: string; args?: unknown } }
  | { type: "system.models.download_progress"; data: any }
  | { type: "system.models.download_complete"; data?: any };

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

export type CapabilityRisk = "low" | "med" | "high";

/** One plain-language permission line derived from a manifest capability id. */
export interface AgentCapability {
  id: string;
  label: string;
  risk: CapabilityRisk;
}

/** Consent-disclosure payload: GET /agents/{name}/capabilities. `sensitive`
    is true iff any capability is "high" or "med" (personal-data read/write). */
export interface AgentCapabilities {
  name: string;
  capabilities: AgentCapability[];
  sensitive: boolean;
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

// --- Community (merged «Сообщество» feed: Supabase UGC ∪ GitHub curated) ---
export type CommunitySource = "ugc" | "curated" | "local";

/** One uniform community card from GET /catalog/community. UGC cards carry a
    slug + social counts; curated cards carry source_id+name for GitHub install. */
export interface CommunityCard {
  source: CommunitySource;
  slug: string;
  name: string;
  description: string;
  category: string | null;
  version: string;
  creator_id: string | null;
  creator_handle: string | null;
  install_count: number;
  like_count: number;
  rating_count: number;
  avg_rating: number;
  liked: boolean;
  rated: number | null;
  installed: boolean;
  source_id: string | null;
  trust: string;
}

/** Aggregate social signal for a skill (GET /catalog/{slug}/social). */
export interface CommunitySocial {
  status?: string;
  like_count: number;
  rating_count: number;
  avg_rating: number;
  liked: boolean;
  rated: number | null;
}

/** A public (approved) comment row (GET /catalog/{slug}/comments). */
export interface CommunityComment {
  id?: string;
  skill_id?: string;
  user_id?: string;
  body: string;
  status?: string;
  created_at?: string;
}

/** Current KALI account session (GET /community/account). */
export interface CommunityAccount {
  signed_in: boolean;
  account_id: string | null;
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

// --- Live Canvas ---
export interface CanvasWidget {
  id: string;
  type: "stat_card" | "bar_chart" | "line_chart" | "progress" | "table" | "markdown";
  title: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}
