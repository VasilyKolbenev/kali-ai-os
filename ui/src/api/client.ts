import { resolveApiUrl, type HttpMethod } from "./endpoints";

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const method = ((options?.method ?? "GET").toUpperCase()) as HttpMethod;
  const res = await fetch(resolveApiUrl(path, method), {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

type Primitive = string | number | boolean | null;
type DeepPartial<T> = T extends Primitive
  ? T
  : T extends Array<infer U>
    ? Array<DeepPartial<U>>
    : { [K in keyof T]?: DeepPartial<T[K]> };

export const api = {
  health: () => fetchJSON<import("./types").HealthResponse>("/health"),
  agents: () => fetchJSON<import("./types").AgentManifest[]>("/agents"),
  agentTools: () => fetchJSON<unknown[]>("/agents/tools"),
  runningAgents: () => fetchJSON<import("./types").AgentStatus[]>("/agents/running"),
  loadAgent: (name: string) => fetchJSON<{ status: string }>(`/agents/${name}/load`, { method: "POST" }),
  unloadAgent: (name: string) => fetchJSON<{ status: string }>(`/agents/${name}/unload`, { method: "POST" }),
  // M2.2: revoke a granted consent (sticky — denied until explicitly re-enabled
  // via loadAgent). agentConsents reads durable {name: 'approved'|'revoked'}.
  revokeAgent: (name: string) =>
    fetchJSON<{ status: string; agent: string }>(`/agents/${name}/revoke`, { method: "POST" }),
  agentConsents: () =>
    fetchJSON<Record<string, "approved" | "revoked">>("/agents/consents"),
  agentStatus: (name: string) => fetchJSON<import("./types").AgentStatus>(`/agents/${name}/status`),
  getCapabilities: (name: string) =>
    fetchJSON<import("./types").AgentCapabilities>(`/agents/${name}/capabilities`),
  chat: (text: string) => fetchJSON<{ response: string; source: string; data?: unknown }>("/chat", {
    method: "POST",
    body: JSON.stringify({ text }),
  }),
  config: () => fetchJSON<Record<string, unknown>>("/config"),
  updateConfig: (patch: DeepPartial<Record<string, unknown>>) =>
    fetchJSON<Record<string, unknown>>("/config", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
  voiceStatus: () => fetchJSON<import("./types").VoiceStatus>("/voice/status"),
  testApiKey: (provider: string, apiKey: string) =>
    fetchJSON<{ ok: boolean; error?: string }>("/llm/test", {
      method: "POST",
      body: JSON.stringify({ provider, api_key: apiKey }),
    }),
  voiceStart: () => fetchJSON<{ status: string }>("/voice/start", { method: "POST" }),
  voiceStop: () => fetchJSON<{ status: string }>("/voice/stop", { method: "POST" }),

  // Models downloading (Onboarding)
  modelsStatus: () => fetchJSON<{
    ready: boolean;
    missing_downloadable: string[];
    missing_bundled: string[];
    models_dir: string;
  }>("/models/status"),
  modelsDownload: () => fetchJSON<{ status: string; message: string }>("/models/download", { method: "POST" }),

  // Legacy Catalog / Store (kept for backward compat)
  skills: () => fetchJSON<any[]>("/skills"),
  catalogSearch: (q: string) =>
    fetchJSON<{ results: any[]; count: number }>(
      `/catalog/search?q=${encodeURIComponent(q)}`,
    ),
  catalogTrending: () => fetchJSON<{ results: any[] }>("/catalog/trending"),
  catalogPack: (name: string) =>
    fetchJSON<any>(`/catalog/pack/${name}`, { method: "POST" }),
  catalogInstall: (path: string) =>
    fetchJSON<any>("/catalog/install", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),

  // Agent Skills (SKILL.md spec) — new in Phase 3+
  skillsCatalogSources: () =>
    fetchJSON<{ sources: import("./types").CatalogSource[] }>("/skills/catalog/sources"),
  skillsCatalogList: (source?: string, q?: string) => {
    const params = new URLSearchParams();
    if (source) params.set("source", source);
    if (q) params.set("q", q);
    const qs = params.toString();
    return fetchJSON<{ results: import("./types").CatalogSkill[]; count: number }>(
      `/skills/catalog${qs ? "?" + qs : ""}`,
    );
  },
  skillsCatalogRefresh: (force = true) =>
    fetchJSON<{ status: string; total_entries: number }>("/skills/catalog/refresh", {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  skillInstall: (source_id: string, name: string, overwrite = false) =>
    fetchJSON<{ status: string; skill_name?: string; install_path?: string; message?: string; warnings?: string[] }>(
      "/skills/install",
      { method: "POST", body: JSON.stringify({ source_id, name, overwrite }) },
    ),
  skillUninstall: (name: string) =>
    fetchJSON<{ status: string; removed: boolean }>(
      "/skills/uninstall",
      { method: "POST", body: JSON.stringify({ name }) },
    ),
  skillsInstalled: () =>
    fetchJSON<{ results: import("./types").InstalledSkill[]; count: number }>(
      "/skills/installed",
    ),
  skillValidate: (name: string) =>
    fetchJSON<{ status: string; skill_name: string; valid: boolean; errors: string[]; warnings: string[] }>(
      "/skills/validate",
      { method: "POST", body: JSON.stringify({ name }) },
    ),
  skillPublish: (name: string, skipSafety = false) =>
    fetchJSON<{
      status: string;
      skill_name: string;
      ok: boolean;
      errors: string[];
      warnings: string[];
      safety_issues: string[];
      catalog_repo_url: string;
      instructions: string[];
      bundle_path?: string;
      bundle_name?: string;
    }>("/skills/publish", {
      method: "POST",
      body: JSON.stringify({ name, skip_safety: skipSafety }),
    }),

  // Sandbox / Audit (Phase 6)
  sandboxHealth: () =>
    fetchJSON<import("./types").SandboxHealth>("/sandbox/health"),
  sandboxAudit: (opts: { agent?: string; status?: string; hours?: number; limit?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.agent) params.set("agent", opts.agent);
    if (opts.status) params.set("status", opts.status);
    if (opts.hours !== undefined) params.set("hours", String(opts.hours));
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return fetchJSON<{
      results: import("./types").AuditRecord[];
      count: number;
      since_hours: number;
    }>(`/sandbox/audit${qs ? "?" + qs : ""}`);
  },
  sandboxStats: (hours = 24) =>
    fetchJSON<{
      results: import("./types").AuditAgentStats[];
      count: number;
      since_hours: number;
    }>(`/sandbox/stats?hours=${hours}`),
  builderClassify: (text: string) =>
    fetchJSON<any>("/builder/classify", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  builderCreateSkill: (data: any) =>
    fetchJSON<any>("/builder/create-skill", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Agent tool execution
  executeAgentTool: (agentName: string, action: string, args: Record<string, unknown> = {}) =>
    fetchJSON<Record<string, unknown>>(`/agents/${agentName}/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, args }),
    }),

  // Live Canvas
  canvasWidgets: () =>
    fetchJSON<{ widgets: import("./types").CanvasWidget[]; count: number }>("/canvas/widgets"),

  // Skill execution
  executeSkill: (skillName: string, action: string, args: Record<string, unknown> = {}) =>
    fetchJSON<Record<string, unknown>>(`/skills/${skillName}/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }),

  // Settings
  settings: () => fetchJSON<Record<string, unknown>>("/settings"),
  updateSettings: (data: Record<string, unknown>) =>
    fetchJSON<Record<string, unknown>>("/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  // Per-agent credential status: { agent: { configured, missing_keys, required_keys } }
  agentConfigStatus: () =>
    fetchJSON<Record<string, { configured: boolean; missing_keys: string[]; required_keys: string[] }>>(
      "/agents/config-status",
    ),
};
