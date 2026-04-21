import { apiUrl } from "./runtime";

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(apiUrl(path), {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  health: () => fetchJSON<import("./types").HealthResponse>("/health"),
  agents: () => fetchJSON<import("./types").AgentManifest[]>("/agents"),
  agentTools: () => fetchJSON<unknown[]>("/agents/tools"),
  runningAgents: () => fetchJSON<import("./types").AgentStatus[]>("/agents/running"),
  loadAgent: (name: string) => fetchJSON<{ status: string }>(`/agents/${name}/load`, { method: "POST" }),
  unloadAgent: (name: string) => fetchJSON<{ status: string }>(`/agents/${name}/unload`, { method: "POST" }),
  agentStatus: (name: string) => fetchJSON<import("./types").AgentStatus>(`/agents/${name}/status`),
  chat: (text: string) => fetchJSON<{ response: string; source: string; data?: unknown }>("/chat", {
    method: "POST",
    body: JSON.stringify({ text }),
  }),
  config: () => fetchJSON<Record<string, unknown>>("/config"),
  voiceStatus: () => fetchJSON<import("./types").VoiceStatus>("/voice/status"),
  voiceStart: () => fetchJSON<{ status: string }>("/voice/start", { method: "POST" }),
  voiceStop: () => fetchJSON<{ status: string }>("/voice/stop", { method: "POST" }),

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
};
