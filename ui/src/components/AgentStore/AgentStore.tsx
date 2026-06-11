import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Search, Sparkles, Wrench, X } from "lucide-react";
import { api } from "../../api/client";
import type { CatalogSkill, CatalogSource, InstalledSkill } from "../../api/types";
import { useAppStore } from "../../stores/appStore";
import { CURATED, type CategoryId, type CuratedEntry } from "./curated";
import { CommunitySection, CuratedStore } from "./CuratedStore";
import { MineSection, type MyAgent } from "./StoreMine";
import { SetupDialog, type CardState } from "./StoreCards";
import { AdvancedStore, PublishDialog, type PublishDialogState } from "./AdvancedStore";

type ToastType = "success" | "error" | "info";
type ViewId = "main" | "advanced";
type SectionId = "mine" | "showcase" | "community";

const COMMUNITY_SOURCE_ID = "kali";

const SECTIONS: { id: SectionId; label: string }[] = [
  { id: "mine", label: "Мои" },
  { id: "showcase", label: "Витрина" },
  { id: "community", label: "Сообщество" },
];

/** «Мастерская» — one home for the whole loop:
    создать своих → делиться (или нет) → брать идеи у других. */
export function AgentStore() {
  const [view, setView] = useState<ViewId>("main");
  const [section, setSection] = useState<SectionId>("showcase");
  const [category, setCategory] = useState<CategoryId>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Shared data
  const [installed, setInstalled] = useState<InstalledSkill[]>([]);
  const [agentNames, setAgentNames] = useState<Set<string>>(new Set());
  const [runningAgents, setRunningAgents] = useState<Set<string>>(new Set());
  const [busyId, setBusyId] = useState<string | null>(null);
  const [setupEntry, setSetupEntry] = useState<CuratedEntry | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: ToastType } | null>(null);

  // Community (kali source)
  const [community, setCommunity] = useState<CatalogSkill[]>([]);
  const [communityLoading, setCommunityLoading] = useState(false);
  const communityLoadedRef = useRef(false);

  // Advanced view
  const [sources, setSources] = useState<CatalogSource[]>([]);
  const [advancedTab, setAdvancedTab] = useState<string>("installed");
  const [catalogSkills, setCatalogSkills] = useState<CatalogSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [installingName, setInstallingName] = useState<string | null>(null);
  const [publishState, setPublishState] = useState<PublishDialogState | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const sourcesLoadedRef = useRef(false);

  useEffect(() => {
    void bootstrap();
  }, []);

  const bootstrap = async () => {
    try {
      const [installedRes, manifests, running] = await Promise.all([
        api.skillsInstalled(),
        api.agents(),
        api.runningAgents(),
      ]);
      setInstalled(installedRes.results || []);
      setAgentNames(new Set((manifests || []).map((m) => m.name)));
      setRunningAgents(new Set((running || []).map((r) => r.name)));
    } catch (err) {
      console.error("Store bootstrap failed:", err);
    }
  };

  // Lazy community fetch on first visit
  useEffect(() => {
    if (section !== "community" || communityLoadedRef.current) return;
    communityLoadedRef.current = true;
    void (async () => {
      setCommunityLoading(true);
      try {
        const res = await api.skillsCatalogList(COMMUNITY_SOURCE_ID, "");
        setCommunity(res.results || []);
      } catch {
        setCommunity([]); // graceful: empty state invites to publish first
      }
      setCommunityLoading(false);
    })();
  }, [section]);

  // Advanced: load sources once, then catalog per tab/search
  useEffect(() => {
    if (view !== "advanced" || sourcesLoadedRef.current) return;
    sourcesLoadedRef.current = true;
    void (async () => {
      try {
        const res = await api.skillsCatalogSources();
        setSources(res.sources || []);
      } catch (err) {
        showToast(`Не удалось получить источники: ${(err as Error).message}`, "error");
      }
    })();
  }, [view]);

  useEffect(() => {
    if (view !== "advanced" || advancedTab === "installed") return;
    void loadCatalogForTab(advancedTab, searchQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advancedTab, view]);

  const loadCatalogForTab = async (source: string, q: string) => {
    setLoading(true);
    try {
      const res = await api.skillsCatalogList(source, q);
      setCatalogSkills(res.results || []);
    } catch (err) {
      setCatalogSkills([]);
      showToast(`Каталог не загрузился: ${(err as Error).message}`, "error");
    }
    setLoading(false);
  };

  const handleQueryChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (view === "advanced" && advancedTab !== "installed") {
      debounceRef.current = setTimeout(() => {
        void loadCatalogForTab(advancedTab, value);
      }, 300);
    }
  };

  const refreshInstalled = async () => {
    const inst = await api.skillsInstalled();
    setInstalled(inst.results || []);
  };

  const refreshRunning = async () => {
    const running = await api.runningAgents();
    setRunningAgents(new Set((running || []).map((r) => r.name)));
  };

  // --- Витрина actions --------------------------------------------------

  const installedNames = useMemo(
    () => new Set(installed.map((s) => s.name)),
    [installed],
  );

  const curatedEntries = useMemo(
    () => CURATED.filter(
      (e) => e.kind !== "agent" || agentNames.size === 0 || agentNames.has(e.agentName!)),
    [agentNames],
  );

  const myAgents: MyAgent[] = useMemo(
    () => [...agentNames].map((name) => ({ name, running: runningAgents.has(name) })),
    [agentNames, runningAgents],
  );

  const entryState = (entry: CuratedEntry): CardState => {
    if (busyId === entry.id) return "busy";
    if (entry.kind === "agent") {
      return runningAgents.has(entry.agentName!) ? "active" : "idle";
    }
    return installedNames.has(entry.source!.name) ? "active" : "idle";
  };

  const handleCuratedPrimary = async (entry: CuratedEntry) => {
    setBusyId(entry.id);
    try {
      if (entry.kind === "agent") {
        await api.loadAgent(entry.agentName!);
        await refreshRunning();
        showToast(`«${entry.title}» работает`, "success");
      } else {
        const res = await api.skillInstall(entry.source!.sourceId, entry.source!.name);
        if (res.status === "ok") {
          await refreshInstalled();
          showToast(`«${entry.title}» установлен`, "success");
        } else {
          showToast(res.message || "Не получилось установить", "error");
        }
      }
      if (entry.setup) setSetupEntry(entry);
    } catch (err) {
      showToast(`Не получилось: ${(err as Error).message}`, "error");
    }
    setBusyId(null);
  };

  // --- Мои actions -------------------------------------------------------

  const handleToggleAgent = async (agent: MyAgent) => {
    setBusyId(agent.name);
    try {
      await api.unloadAgent(agent.name);
      await refreshRunning();
      showToast("Помощник остановлен", "info");
    } catch (err) {
      showToast(`Не получилось: ${(err as Error).message}`, "error");
    }
    setBusyId(null);
  };

  const handleInstallCommunity = async (skill: CatalogSkill) => {
    setInstallingName(skill.name);
    try {
      const res = await api.skillInstall(skill.source_id, skill.name);
      if (res.status === "ok") {
        await refreshInstalled();
        showToast(`«${skill.name}» установлен`, "success");
      } else {
        showToast(res.message || "Не получилось установить", "error");
      }
    } catch (err) {
      showToast(`Не получилось: ${(err as Error).message}`, "error");
    }
    setInstallingName(null);
  };

  // --- Advanced actions (unchanged behavior, RU strings) -----------------

  const handleRefreshCatalog = async () => {
    setRefreshing(true);
    try {
      const res = await api.skillsCatalogRefresh(true);
      showToast(`Каталог обновлён: ${res.total_entries} навыков`, "success");
      if (advancedTab !== "installed") {
        await loadCatalogForTab(advancedTab, searchQuery);
      }
      communityLoadedRef.current = false; // re-fetch community next visit
    } catch (err) {
      showToast(`Не удалось обновить: ${(err as Error).message}`, "error");
    }
    setRefreshing(false);
  };

  const handleInstall = async (skill: CatalogSkill) => {
    setInstallingName(skill.name);
    try {
      const res = await api.skillInstall(skill.source_id, skill.name);
      if (res.status === "ok") {
        showToast(`«${skill.name}» установлен`, "success");
        await refreshInstalled();
      } else {
        showToast(res.message || "Не получилось установить", "error");
      }
    } catch (err) {
      showToast(`Ошибка установки: ${(err as Error).message}`, "error");
    }
    setInstallingName(null);
  };

  const handleUninstall = async (skill: InstalledSkill) => {
    if (!confirm(`Удалить навык «${skill.name}»?`)) return;
    try {
      const res = await api.skillUninstall(skill.name);
      if (res.removed) {
        showToast(`«${skill.name}» удалён`, "success");
        await refreshInstalled();
      } else {
        showToast("Навык не найден или защищён от удаления", "error");
      }
    } catch (err) {
      showToast(`Ошибка удаления: ${(err as Error).message}`, "error");
    }
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

  const showToast = (msg: string, type: ToastType = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

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
          <Wrench className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Мастерская
          </h2>
          <button
            onClick={() => useAppStore.getState().setMode("builder")}
            className="ml-auto px-3 py-1.5 text-xs font-medium rounded-lg bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30 transition flex items-center gap-1.5 border border-[var(--j-cyan)]/30"
            title="Создать свой навык голосом"
          >
            <Sparkles className="w-3.5 h-3.5" />
            Создать голосом
          </button>
        </div>

        {/* Search */}
        <div className="glass p-4 mb-6 flex gap-3 items-center rounded-2xl relative overflow-hidden group">
          <Search className="w-5 h-5 text-white/40 shrink-0 group-focus-within:text-[var(--j-cyan)] transition-colors" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Найти: напомнить пить воду, погода, курс доллара…"
            className="flex-1 bg-transparent outline-none text-base placeholder:text-white/20"
          />
          {searchQuery && (
            <button onClick={() => handleQueryChange("")} className="text-white/30 hover:text-white/60 p-1">
              <X className="w-4 h-4" />
            </button>
          )}
          {loading && <Loader2 className="w-5 h-5 text-[var(--j-cyan)] animate-spin" />}
        </div>

        {view === "main" ? (
          <>
            {/* Создать своих · делиться или нет · брать идеи у других */}
            <div className="flex gap-1 mb-6 bg-white/5 p-1 rounded-xl w-fit border border-white/10">
              {SECTIONS.map((s) => (
                <button
                  key={s.id}
                  onClick={() => setSection(s.id)}
                  className={`px-4 py-1.5 text-sm rounded-lg transition-all
                    ${section === s.id
                      ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)]"
                      : "text-white/40 hover:text-white/80"
                    }`}
                >
                  {s.label}
                </button>
              ))}
            </div>

            {section === "mine" && (
              <MineSection
                agents={myAgents}
                skills={installed}
                busyAgent={busyId}
                onToggleAgent={handleToggleAgent}
                onPublish={handlePublish}
                onUninstall={handleUninstall}
                searchQuery={searchQuery}
              />
            )}
            {section === "showcase" && (
              <CuratedStore
                category={category}
                onCategory={setCategory}
                searchQuery={searchQuery}
                entries={curatedEntries}
                entryState={entryState}
                onPrimary={handleCuratedPrimary}
                onSetup={setSetupEntry}
              />
            )}
            {section === "community" && (
              <CommunitySection
                skills={community}
                loading={communityLoading}
                installedNames={installedNames}
                installingName={installingName}
                onInstall={handleInstallCommunity}
                searchQuery={searchQuery}
              />
            )}
          </>
        ) : (
          <AdvancedStore
            activeTab={advancedTab}
            onTab={setAdvancedTab}
            sources={sources}
            installed={installed}
            catalogSkills={catalogSkills}
            loading={loading}
            refreshing={refreshing}
            installedNames={installedNames}
            installingName={installingName}
            searchQuery={searchQuery}
            onRefresh={handleRefreshCatalog}
            onInstall={handleInstall}
            onUninstall={handleUninstall}
            onPublish={handlePublish}
          />
        )}

        {/* View toggle — intentionally quiet */}
        <div className="mt-8 text-center">
          <button
            onClick={() => setView(view === "main" ? "advanced" : "main")}
            className="text-xs text-white/30 hover:text-white/60 transition underline-offset-4 hover:underline"
          >
            {view === "main" ? "Для продвинутых: источники и публикация ›" : "‹ Вернуться в Мастерскую"}
          </button>
        </div>

        {setupEntry && (
          <SetupDialog entry={setupEntry} onClose={() => setSetupEntry(null)} />
        )}

        {publishState && (
          <PublishDialog state={publishState} onClose={() => setPublishState(null)} />
        )}

        {toast && (
          <div
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 glass px-4 py-2 rounded-lg text-sm flex items-center gap-2"
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
