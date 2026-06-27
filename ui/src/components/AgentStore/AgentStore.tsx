import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Search, Sparkles, Wrench, X } from "lucide-react";
import { api } from "../../api/client";
import type {
  AgentCapability, CatalogSkill, CatalogSource,
  CommunityCard as CommunityCardData, InstalledSkill,
} from "../../api/types";
import { useAppStore } from "../../stores/appStore";
import { CURATED, type CategoryId, type CuratedEntry } from "./curated";
import { CommunitySection, CuratedStore } from "./CuratedStore";
import { MineSection, type MyAgent } from "./StoreMine";
import { SetupDialog, type CardState } from "./StoreCards";
import { ConsentDialog } from "./ConsentDialog";
import { MagicLinkDialog } from "./MagicLinkDialog";
import { AdvancedStore, PublishDialog, type PublishDialogState } from "./AdvancedStore";

type ToastType = "success" | "error" | "info";
type ViewId = "main" | "advanced";
type SectionId = "mine" | "showcase" | "community";

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
  const [configStatus, setConfigStatus] = useState<
    Record<string, { configured: boolean; missing_keys: string[]; required_keys: string[] }>
  >({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [setupEntry, setSetupEntry] = useState<CuratedEntry | null>(null);
  const [consent, setConsent] = useState<{ entry: CuratedEntry; capabilities: AgentCapability[] } | null>(null);
  const [consents, setConsents] = useState<Record<string, "approved" | "revoked">>({});
  const [toast, setToast] = useState<{ msg: string; type: ToastType } | null>(null);

  // Community (merged Supabase UGC ∪ GitHub curated ∪ local)
  const [community, setCommunity] = useState<CommunityCardData[]>([]);
  const [communityLoading, setCommunityLoading] = useState(false);
  const communityLoadedRef = useRef(false);
  // Magic-link sign-in prompt — raised when a signed-out rate/comment returns
  // "sign-in required" (honest, not a fake success). NOT OAuth.
  const [signInReason, setSignInReason] = useState<string | null>(null);

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
      const [installedRes, manifests, running, cfg, cons] = await Promise.all([
        api.skillsInstalled(),
        api.agents(),
        api.runningAgents(),
        api.agentConfigStatus().catch(() => ({})),
        api.agentConsents().catch(() => ({})),
      ]);
      setInstalled(installedRes.results || []);
      setAgentNames(new Set((manifests || []).map((m) => m.name)));
      setRunningAgents(new Set((running || []).map((r) => r.name)));
      setConfigStatus(cfg || {});
      setConsents(cons || {});
    } catch (err) {
      console.error("Store bootstrap failed:", err);
    }
  };

  const refreshConfigStatus = async () => {
    try {
      setConfigStatus(await api.agentConfigStatus());
    } catch {
      /* leave previous */
    }
  };

  // After keys are saved in the setup dialog: refresh status + auto-enable the
  // agent so it flips straight to «Работает».
  const handleSetupSaved = async (entry: CuratedEntry) => {
    await refreshConfigStatus();
    if (entry.kind === "agent" && entry.agentName) {
      try {
        await api.loadAgent(entry.agentName);
        await refreshRunning();
        showToast(`«${entry.title}» настроен и работает`, "success");
      } catch {
        showToast(`«${entry.title}» настроен`, "success");
      }
    }
  };

  // Lazy community fetch on first visit — the merged feed (Supabase UGC ∪
  // GitHub curated ∪ local), deduped server-side. Degrades to the empty-state
  // invite when the route is unreachable (no error wall).
  useEffect(() => {
    if (section !== "community" || communityLoadedRef.current) return;
    communityLoadedRef.current = true;
    void (async () => {
      setCommunityLoading(true);
      try {
        const res = await api.catalogCommunity("");
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

  const refreshConsents = async () => {
    try {
      setConsents(await api.agentConsents());
    } catch {
      /* leave previous */
    }
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
      // Needs a key it doesn't have yet → «Настроить», not a fake «Работает».
      if (entry.setup?.keys?.length) {
        const cfg = configStatus[entry.agentName!];
        if (cfg && !cfg.configured) return "needs-setup";
      }
      return runningAgents.has(entry.agentName!) ? "active" : "idle";
    }
    return installedNames.has(entry.source!.name) ? "active" : "idle";
  };

  // Does the actual enabling — the same path for one-click and post-consent.
  const enableEntry = async (entry: CuratedEntry) => {
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

  // Consent gate: agents with sensitive capabilities (personal-data read/write)
  // disclose first; weather/currency/skills keep today's one-click. Disclosure
  // only — «Разрешить» runs the same enableEntry path. Fail-open: if the
  // capabilities lookup is unavailable, fall through to direct enable.
  const handleCuratedPrimary = async (entry: CuratedEntry) => {
    if (entry.kind === "agent" && entry.agentName) {
      setBusyId(entry.id);
      try {
        const caps = await api.getCapabilities(entry.agentName);
        if (caps.sensitive) {
          setConsent({ entry, capabilities: caps.capabilities });
          setBusyId(null);
          return;
        }
      } catch {
        /* fail-open: keep today's one-click enable */
      }
      setBusyId(null);
    }
    await enableEntry(entry);
  };

  const handleConsentAllow = async () => {
    if (!consent) return;
    const { entry } = consent;
    setConsent(null);
    await enableEntry(entry);
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

  // M2.2: take back / restore an agent's access to personal data. Revoke is
  // sticky (persisted, denied until re-enabled); re-enable runs the explicit
  // approve path (loadAgent) which clears the sticky revoke.
  const handleRevokeAgent = async (agent: MyAgent) => {
    setBusyId(agent.name);
    try {
      await api.revokeAgent(agent.name);
      await refreshConsents();
      showToast("Доступ отозван", "info");
    } catch (err) {
      showToast(`Не получилось: ${(err as Error).message}`, "error");
    }
    setBusyId(null);
  };

  const handleReenableAgent = async (agent: MyAgent) => {
    setBusyId(agent.name);
    try {
      await api.loadAgent(agent.name);
      await Promise.all([refreshRunning(), refreshConsents()]);
      showToast("Доступ снова разрешён", "success");
    } catch (err) {
      showToast(`Не получилось: ${(err as Error).message}`, "error");
    }
    setBusyId(null);
  };

  // Install a community card: UGC (Supabase slug) via the bundle-download route,
  // curated (GitHub source_id+name) via the existing skill-install path.
  const handleInstallCommunity = async (card: CommunityCardData) => {
    setInstallingName(card.name);
    try {
      const res = card.source === "ugc" && card.slug
        ? await api.catalogCommunityInstall(card.slug)
        : await api.skillInstall(card.source_id || "", card.name);
      if (res.status === "ok") {
        await refreshInstalled();
        showToast(`«${card.name}» установлен`, "success");
      } else if (res.status === "unconfigured") {
        showToast("Каталог сообщества пока недоступен", "info");
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
                consents={consents}
                onToggleAgent={handleToggleAgent}
                onRevoke={handleRevokeAgent}
                onReenable={handleReenableAgent}
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
                cards={community}
                loading={communityLoading}
                installedNames={installedNames}
                installingName={installingName}
                onInstall={handleInstallCommunity}
                onRequireSignIn={setSignInReason}
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

        {consent && (
          <ConsentDialog
            entry={consent.entry}
            capabilities={consent.capabilities}
            onAllow={handleConsentAllow}
            onCancel={() => setConsent(null)}
          />
        )}

        {setupEntry && (
          <SetupDialog
            entry={setupEntry}
            onClose={() => setSetupEntry(null)}
            onSaved={() => handleSetupSaved(setupEntry)}
          />
        )}

        {signInReason && (
          <MagicLinkDialog
            reason={signInReason}
            onClose={() => setSignInReason(null)}
            onSignedIn={() => showToast("Вход выполнен", "success")}
          />
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
