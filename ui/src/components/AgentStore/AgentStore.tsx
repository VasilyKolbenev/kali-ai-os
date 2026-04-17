import { useEffect, useState, useRef, useCallback } from "react";
import { Search, Download, Package, Sparkles, Zap, Check, Loader2, X } from "lucide-react";
import { api } from "../../api/client";
import { useAppStore } from "../../stores/appStore";

interface SkillInfo {
  name: string;
  template: string;
  display_name: string;
  config: Record<string, unknown>;
}

interface CatalogItem {
  name: string;
  description: string;
  type: string;
  category: string;
  downloads: number;
  rating_avg: number;
  trust_level: string;
  installed?: boolean;
}

type ToastType = "success" | "error" | "info";

export function AgentStore() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [catalogResults, setCatalogResults] = useState<CatalogItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [loading, setLoading] = useState(false);
  const [installingName, setInstallingName] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: ToastType } | null>(null);
  const setMode = useAppStore((s) => s.setMode);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const showToast = (msg: string, type: ToastType = "info") => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  };

  const loadTrending = async () => {
    try {
      const data = await api.catalogTrending();
      setCatalogResults(data.results || []);
    } catch {
      // catalog not configured
    }
  };

  const reloadSkills = async () => {
    try {
      const data = await api.skills();
      setSkills(data);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    reloadSkills();
    loadTrending();
  }, []);

  // Live search with debounce (300ms)
  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setIsSearching(false);
      await loadTrending();
      return;
    }
    setIsSearching(true);
    setLoading(true);
    try {
      const data = await api.catalogSearch(q);
      setCatalogResults(data.results || []);
    } catch {
      setCatalogResults([]);
    }
    setLoading(false);
  }, []);

  const handleQueryChange = (value: string) => {
    setSearchQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(value), 300);
  };

  const handleInstall = async (item: CatalogItem) => {
    setInstallingName(item.name);
    try {
      await api.catalogInstall(item.name);
      showToast(`«${item.name}» установлен`, "success");
      // Mark as installed in local state
      setCatalogResults((prev) =>
        prev.map((r) => (r.name === item.name ? { ...r, installed: true } : r))
      );
      await reloadSkills();
    } catch (err) {
      showToast(`Ошибка установки: ${(err as Error).message}`, "error");
    }
    setInstallingName(null);
  };

  const toastColor = toast?.type === "success"
    ? "var(--j-green)"
    : toast?.type === "error"
      ? "var(--j-red, #ef4444)"
      : "var(--j-cyan)";

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-6">
          <Package className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Agent Store
          </h2>
          <span
            className="mono text-[10px] tracking-widest uppercase ml-auto"
            style={{ color: "var(--j-text-muted)" }}
          >
            {skills.length} installed
          </span>
        </div>

        {/* Search — live, no button needed */}
        <div className="glass p-3 mb-6 flex gap-2 items-center">
          <Search className="w-4 h-4 text-white/40 shrink-0" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Поиск агентов и навыков..."
            className="flex-1 bg-transparent outline-none text-sm placeholder:text-white/20"
          />
          {searchQuery && (
            <button
              onClick={() => { setSearchQuery(""); doSearch(""); }}
              className="text-white/30 hover:text-white/60"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          {loading && <Loader2 className="w-4 h-4 text-[var(--j-cyan)] animate-spin" />}
        </div>

        {/* Installed Skills */}
        <div className="mb-8">
          <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
            Установленные
          </h3>
          <div className="grid gap-2 stagger">
            {skills.length === 0 && (
              <div className="glass p-4 text-sm text-white/30">
                Навыки ещё не установлены
              </div>
            )}
            {skills.map((skill) => (
              <div key={skill.name} className="glass p-4 flex items-center gap-3">
                <Sparkles className="w-4 h-4 text-[var(--j-green)]" />
                <div className="flex-1">
                  <div className="text-sm font-medium">
                    {skill.display_name || skill.name}
                  </div>
                  <div className="text-xs text-white/40">
                    {skill.template}
                  </div>
                </div>
                <span className="text-xs px-2 py-0.5 rounded bg-[var(--j-green)]/10 text-[var(--j-green)]">
                  Активен
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Catalog Results */}
        {catalogResults.length > 0 && (
          <div>
            <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
              {isSearching ? "Результаты поиска" : "Популярные"}
            </h3>
            <div className="grid gap-2 stagger">
              {catalogResults.map((item) => (
                <div key={item.name} className="glass p-4 flex items-center gap-3">
                  <Zap className="w-4 h-4 text-[var(--j-cyan)]" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{item.name}</div>
                    <div className="text-xs text-white/40 truncate">{item.description}</div>
                    <div className="text-xs text-white/20 mt-1">
                      {item.category} &middot; {item.downloads} &middot;{" "}
                      &#9733; {item.rating_avg?.toFixed(1)}
                    </div>
                  </div>
                  {item.installed ? (
                    <button
                      onClick={() => setMode("agents")}
                      className="px-3 py-1 text-xs rounded bg-[var(--j-green)]/10
                        text-[var(--j-green)] hover:bg-[var(--j-green)]/20
                        transition flex items-center gap-1 shrink-0"
                    >
                      <Check className="w-3 h-3" />
                      Настроить
                    </button>
                  ) : (
                    <button
                      disabled={installingName === item.name}
                      onClick={() => handleInstall(item)}
                      className="px-3 py-1 text-xs rounded bg-[var(--j-cyan)]/20
                        text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30
                        transition flex items-center gap-1 shrink-0
                        disabled:opacity-50 disabled:cursor-wait"
                    >
                      {installingName === item.name ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Download className="w-3 h-3" />
                      )}
                      {installingName === item.name ? "Установка..." : "Установить"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty state */}
        {!loading && catalogResults.length === 0 && isSearching && (
          <div className="text-center text-sm text-white/30 py-8">
            Ничего не найдено
          </div>
        )}

        {/* Toast notification */}
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
