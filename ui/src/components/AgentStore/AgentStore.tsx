import { useEffect, useMemo, useRef, useState } from "react";
import {
  Search, Download, Package, Sparkles, Check, Loader2, X,
  RefreshCw, Shield, Trash2, ExternalLink, Upload, AlertCircle,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  CatalogSkill, CatalogSource, InstalledSkill,
} from "../../api/types";

interface PublishDialogState {
  skillName: string;
  phase: "validating" | "publishing" | "success" | "error";
  errors: string[];
  warnings: string[];
  instructions: string[];
  catalogRepoUrl: string;
  bundlePath: string;
}

type TabId = "installed" | string; // source_id or "installed"
type ToastType = "success" | "error" | "info";

const TRUST_COLORS: Record<string, string> = {
  official: "var(--j-green)",
  verified: "var(--j-cyan)",
  community: "var(--j-amber, #f59e0b)",
};

const TRUST_LABELS: Record<string, string> = {
  official: "Official",
  verified: "Verified",
  community: "Community",
};

export function AgentStore() {
  const [activeTab, setActiveTab] = useState<TabId>("installed");
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [installed, setInstalled] = useState<InstalledSkill[]>([]);
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [installingName, setInstallingName] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: ToastType } | null>(null);
  const [publishState, setPublishState] = useState<PublishDialogState | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Boot: load sources + installed skills + trigger first catalog fetch
  useEffect(() => {
    void bootstrap();
  }, []);

  const bootstrap = async () => {
    try {
      const [sourcesRes, installedRes] = await Promise.all([
        api.skillsCatalogSources(),
        api.skillsInstalled(),
      ]);
      setSources(sourcesRes.sources || []);
      setInstalled(installedRes.results || []);
    } catch (err) {
      console.error("Failed to bootstrap Agent Store:", err);
    }
  };

  // Reload catalog entries when tab or search changes
  useEffect(() => {
    if (activeTab === "installed") return;
    void loadCatalogForTab(activeTab, searchQuery);
  }, [activeTab]);

  const loadCatalogForTab = async (source: string, q: string) => {
    setLoading(true);
    try {
      const res = await api.skillsCatalogList(source, q);
      setCatalogSkills(res.results || []);
    } catch (err) {
      setCatalogSkills([]);
      showToast(`Failed to load catalog: ${(err as Error).message}`, "error");
    }
    setLoading(false);
  };

  const handleQueryChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (activeTab !== "installed") {
      debounceRef.current = setTimeout(() => {
        void loadCatalogForTab(activeTab, value);
      }, 300);
    }
  };

  const handleRefreshCatalog = async () => {
    setRefreshing(true);
    try {
      const res = await api.skillsCatalogRefresh(true);
      showToast(`Catalog refreshed: ${res.total_entries} skills indexed`, "success");
      if (activeTab !== "installed") {
        await loadCatalogForTab(activeTab, searchQuery);
      }
    } catch (err) {
      showToast(`Refresh failed: ${(err as Error).message}`, "error");
    }
    setRefreshing(false);
  };

  const handleInstall = async (skill: CatalogSkill) => {
    setInstallingName(skill.name);
    try {
      const res = await api.skillInstall(skill.source_id, skill.name);
      if (res.status === "ok") {
        showToast(`«${skill.name}» installed`, "success");
        const inst = await api.skillsInstalled();
        setInstalled(inst.results || []);
      } else {
        showToast(res.message || "Install failed", "error");
      }
    } catch (err) {
      showToast(`Install error: ${(err as Error).message}`, "error");
    }
    setInstallingName(null);
  };

  const handlePublish = async (skill: InstalledSkill) => {
    setPublishState({
      skillName: skill.name,
      phase: "publishing",
      errors: [], warnings: [], instructions: [],
      catalogRepoUrl: "", bundlePath: "",
    });
    try {
      const res = await api.skillPublish(skill.name);
      if (res.ok) {
        setPublishState({
          skillName: res.skill_name,
          phase: "success",
          errors: res.errors || [],
          warnings: res.warnings || [],
          instructions: res.instructions || [],
          catalogRepoUrl: res.catalog_repo_url || "",
          bundlePath: res.bundle_path || "",
        });
      } else {
        setPublishState({
          skillName: res.skill_name || skill.name,
          phase: "error",
          errors: [...(res.errors || []), ...(res.safety_issues || [])],
          warnings: res.warnings || [],
          instructions: [],
          catalogRepoUrl: "", bundlePath: "",
        });
      }
    } catch (err) {
      setPublishState({
        skillName: skill.name,
        phase: "error",
        errors: [(err as Error).message],
        warnings: [], instructions: [],
        catalogRepoUrl: "", bundlePath: "",
      });
    }
  };

  const handleUninstall = async (skill: InstalledSkill) => {
    if (!confirm(`Remove skill «${skill.name}»?`)) return;
    try {
      const res = await api.skillUninstall(skill.name);
      if (res.removed) {
        showToast(`«${skill.name}» removed`, "success");
        const inst = await api.skillsInstalled();
        setInstalled(inst.results || []);
      } else {
        showToast("Skill not found or cannot be removed", "error");
      }
    } catch (err) {
      showToast(`Remove error: ${(err as Error).message}`, "error");
    }
  };

  const showToast = (msg: string, type: ToastType = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const installedNames = useMemo(
    () => new Set(installed.map((s) => s.name)),
    [installed],
  );

  const filteredInstalled = useMemo(() => {
    if (!searchQuery.trim()) return installed;
    const q = searchQuery.toLowerCase();
    return installed.filter(
      (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q),
    );
  }, [installed, searchQuery]);

  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "installed", label: "Установленные", count: installed.length },
    ...sources.map((s) => ({ id: s.id as TabId, label: s.label })),
  ];

  const toastColor = toast?.type === "success"
    ? "var(--j-green)"
    : toast?.type === "error"
      ? "var(--j-red, #ef4444)"
      : "var(--j-cyan)";

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-6">
          <Package className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Agent Skills
          </h2>
          <span
            className="mono text-[10px] tracking-widest uppercase ml-auto"
            style={{ color: "var(--j-text-muted)" }}
          >
            {installed.length} installed
          </span>
          <button
            onClick={handleRefreshCatalog}
            disabled={refreshing}
            className="text-white/40 hover:text-white/80 transition disabled:opacity-50"
            title="Refresh catalog"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>

        {/* Search bar */}
        <div className="glass p-3 mb-4 flex gap-2 items-center">
          <Search className="w-4 h-4 text-white/40 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Поиск: weather, notion, telegram…"
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-white/20"
          />
          {searchQuery && (
            <button
              onClick={() => handleQueryChange("")}
              className="text-white/30 hover:text-white/60"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          {loading && <Loader2 className="w-4 h-4 text-[var(--j-cyan)] animate-spin" />}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 border-b border-white/5">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-2 text-xs tracking-wider uppercase transition relative
                ${activeTab === tab.id
                  ? "text-[var(--j-cyan)]"
                  : "text-white/40 hover:text-white/60"
                }`}
            >
              {tab.label}
              {tab.count !== undefined && (
                <span className="ml-1.5 text-white/30">({tab.count})</span>
              )}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-[var(--j-cyan)]" />
              )}
            </button>
          ))}
        </div>

        {/* Content */}
        {activeTab === "installed" ? (
          <InstalledList
            skills={filteredInstalled}
            onUninstall={handleUninstall}
            onPublish={handlePublish}
          />
        ) : (
          <CatalogList
            skills={catalogSkills}
            installedNames={installedNames}
            installingName={installingName}
            onInstall={handleInstall}
            loading={loading}
            activeSource={sources.find((s) => s.id === activeTab)}
          />
        )}

        {/* Publish dialog */}
        {publishState && (
          <PublishDialog
            state={publishState}
            onClose={() => setPublishState(null)}
          />
        )}

        {/* Toast */}
        {toast && (
          <div
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50
              glass px-4 py-2 rounded-lg text-sm flex items-center gap-2
              animate-[fadeIn_0.2s_ease-out]"
            style={{ borderColor: toastColor, borderWidth: 1, color: toastColor }}
          >
            {toast.type === "success" && <Check className="w-4 h-4" />}
            {toast.type === "error" && <X className="w-4 h-4" />}
            {toast.msg}
          </div>
        )}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------

function InstalledList({
  skills, onUninstall, onPublish,
}: {
  skills: InstalledSkill[];
  onUninstall: (skill: InstalledSkill) => void;
  onPublish: (skill: InstalledSkill) => void;
}) {
  if (skills.length === 0) {
    return (
      <div className="glass p-6 text-center text-sm text-white/30">
        No skills installed. Browse tabs above to install from the catalog.
      </div>
    );
  }

  return (
    <div className="grid gap-2 stagger">
      {skills.map((skill) => (
        <div key={skill.name} className="glass p-4 flex items-center gap-3">
          <Sparkles className="w-4 h-4 text-[var(--j-green)] shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium truncate">{skill.name}</span>
              <SourceBadge source={skill.source} />
            </div>
            <div className="text-xs text-white/40 truncate mt-0.5">
              {skill.description}
            </div>
            {skill.compatibility && (
              <div className="text-[10px] text-white/30 mt-1 flex items-center gap-1">
                <Shield className="w-3 h-3" />
                {skill.compatibility}
              </div>
            )}
          </div>
          <button
            onClick={() => onPublish(skill)}
            className="text-white/30 hover:text-[var(--j-cyan)] transition p-1"
            title="Publish to KALI catalog"
          >
            <Upload className="w-4 h-4" />
          </button>
          {skill.source !== "builtin" && (
            <button
              onClick={() => onUninstall(skill)}
              className="text-white/30 hover:text-red-400 transition p-1"
              title="Uninstall"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          <span
            className="text-xs px-2 py-0.5 rounded bg-[var(--j-green)]/10 text-[var(--j-green)] shrink-0"
          >
            Active
          </span>
        </div>
      ))}
    </div>
  );
}

// -----------------------------------------------------------------------------

function CatalogList({
  skills, installedNames, installingName, onInstall, loading, activeSource,
}: {
  skills: CatalogSkill[];
  installedNames: Set<string>;
  installingName: string | null;
  onInstall: (skill: CatalogSkill) => void;
  loading: boolean;
  activeSource?: CatalogSource;
}) {
  if (loading && skills.length === 0) {
    return (
      <div className="glass p-8 text-center">
        <Loader2 className="w-5 h-5 text-[var(--j-cyan)] animate-spin mx-auto mb-2" />
        <div className="text-xs text-white/40">Loading catalog…</div>
      </div>
    );
  }

  if (skills.length === 0) {
    return (
      <div className="glass p-6 text-sm text-white/30 space-y-3">
        <div>
          No skills indexed yet from <strong>{activeSource?.label}</strong>.
        </div>
        <div className="text-xs">
          Try <strong>Refresh</strong> (top right). First fetch may take a few seconds.
        </div>
        {activeSource && (
          <a
            href={activeSource.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-[var(--j-cyan)] hover:underline"
          >
            <ExternalLink className="w-3 h-3" />
            {activeSource.url}
          </a>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-2 stagger">
      {skills.map((skill) => {
        const installed = installedNames.has(skill.name);
        const isInstalling = installingName === skill.name;
        return (
          <div key={`${skill.source_id}/${skill.name}`} className="glass p-4 flex items-center gap-3">
            <TrustBadge trust={skill.trust} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium truncate">{skill.name}</span>
                <a
                  href={skill.web_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-white/30 hover:text-white/60 shrink-0"
                  title="View on GitHub"
                >
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
              <div className="text-xs text-white/40 truncate mt-0.5">
                {skill.description}
              </div>
              {(skill.license || skill.compatibility) && (
                <div className="text-[10px] text-white/30 mt-1 flex gap-3">
                  {skill.license && <span>license: {skill.license}</span>}
                  {skill.compatibility && <span>compat: {skill.compatibility}</span>}
                </div>
              )}
            </div>
            {installed ? (
              <span className="px-3 py-1 text-xs rounded bg-[var(--j-green)]/10 text-[var(--j-green)] flex items-center gap-1 shrink-0">
                <Check className="w-3 h-3" />
                Installed
              </span>
            ) : (
              <button
                disabled={isInstalling}
                onClick={() => onInstall(skill)}
                className="px-3 py-1 text-xs rounded bg-[var(--j-cyan)]/20
                  text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30
                  transition flex items-center gap-1 shrink-0
                  disabled:opacity-50 disabled:cursor-wait"
              >
                {isInstalling ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Download className="w-3 h-3" />
                )}
                {isInstalling ? "Installing…" : "Install"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

// -----------------------------------------------------------------------------

function TrustBadge({ trust }: { trust: string }) {
  const color = TRUST_COLORS[trust] ?? "var(--j-text-muted)";
  return (
    <span
      className="text-[10px] tracking-widest uppercase px-1.5 py-0.5 rounded shrink-0"
      style={{ color, backgroundColor: color + "15", borderColor: color + "30", borderWidth: 1 }}
    >
      {TRUST_LABELS[trust] ?? trust}
    </span>
  );
}

function PublishDialog({
  state, onClose,
}: {
  state: PublishDialogState;
  onClose: () => void;
}) {
  const copyBundlePath = () => {
    if (state.bundlePath) {
      navigator.clipboard.writeText(state.bundlePath);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm
        flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="glass p-6 max-w-lg w-full rounded-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 mb-4">
          <Upload className="w-5 h-5 text-[var(--j-cyan)]" />
          <h3 className="text-sm font-medium">
            Publish «{state.skillName}»
          </h3>
          <button
            onClick={onClose}
            className="ml-auto text-white/30 hover:text-white/60"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {state.phase === "publishing" && (
          <div className="py-6 flex items-center gap-3 justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--j-cyan)]" />
            <span className="text-sm text-white/60">
              Validating + packaging skill…
            </span>
          </div>
        )}

        {state.phase === "error" && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 text-sm text-red-400">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>Publish failed — fix issues and try again</span>
            </div>
            {state.errors.length > 0 && (
              <ul className="space-y-1.5 text-xs text-white/60 pl-5 list-disc">
                {state.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {state.phase === "success" && (
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-[var(--j-green)]">
              <Check className="w-4 h-4" />
              Bundle ready — follow the steps below
            </div>

            {state.warnings.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] tracking-wider uppercase text-[var(--j-amber,#f59e0b)]">
                  Warnings
                </div>
                <ul className="space-y-1 text-xs text-white/50 pl-4 list-disc">
                  {state.warnings.map((w, i) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              </div>
            )}

            {state.bundlePath && (
              <div className="space-y-1">
                <div className="text-[10px] tracking-wider uppercase text-white/40">
                  Bundle
                </div>
                <div className="flex gap-2 items-center">
                  <code
                    className="text-[11px] px-2 py-1.5 rounded bg-black/40 text-white/70 flex-1 truncate"
                  >
                    {state.bundlePath}
                  </code>
                  <button
                    onClick={copyBundlePath}
                    className="text-xs px-2 py-1.5 rounded bg-[var(--j-cyan)]/20
                      text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30"
                  >
                    Copy
                  </button>
                </div>
              </div>
            )}

            <div className="space-y-1">
              <div className="text-[10px] tracking-wider uppercase text-white/40">
                Next steps
              </div>
              <ol className="space-y-1 text-xs text-white/70 pl-5 list-decimal">
                {state.instructions.map((step, i) => (
                  <li key={i}>{step.replace(/^\d+\.\s*/, "")}</li>
                ))}
              </ol>
            </div>

            {state.catalogRepoUrl && (
              <a
                href={state.catalogRepoUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-xs text-[var(--j-cyan)] hover:underline"
              >
                <ExternalLink className="w-3 h-3" />
                Open catalog repo
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function SourceBadge({ source }: { source: string }) {
  let label = source;
  let color = "var(--j-text-muted)";
  if (source === "builtin") { label = "built-in"; color = "var(--j-cyan)"; }
  else if (source === "user") { label = "installed"; color = "var(--j-green)"; }
  else if (source.startsWith("catalog:")) { label = source.slice(8); color = "var(--j-amber, #f59e0b)"; }
  return (
    <span
      className="text-[9px] tracking-wider uppercase px-1 py-0.5 rounded shrink-0"
      style={{ color, opacity: 0.7 }}
    >
      {label}
    </span>
  );
}
