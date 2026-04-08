export type VoiceState = "idle" | "listening" | "thinking" | "speaking";

export type WSMessage =
  | { type: "voice.state"; data: { state: VoiceState } }
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
}
