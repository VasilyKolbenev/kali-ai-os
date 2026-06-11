import {
  AlertCircle, Check, Download, ExternalLink, Loader2, RefreshCw,
  Shield, Sparkles, Trash2, Upload, X,
} from "lucide-react";
import { motion } from "framer-motion";
import type { CatalogSkill, CatalogSource, InstalledSkill } from "../../api/types";

/* Dev-oriented catalog view (sources, trust, GitHub, publish) — kept intact
   behind «Для продвинутых»; the curated storefront is the default. */

export interface PublishDialogState {
  skillName: string;
  phase: "validating" | "publishing" | "success" | "error";
  errors: string[];
  warnings: string[];
  instructions: string[];
  catalogRepoUrl: string;
  bundlePath: string;
}

type TabId = "installed" | string;

const TRUST_COLORS = new Map<string, string>([
  ["official", "var(--j-green)"],
  ["verified", "var(--j-cyan)"],
  ["community", "var(--j-amber, #f59e0b)"],
]);

const TRUST_LABELS = new Map<string, string>([
  ["official", "Официальный"],
  ["verified", "Проверенный"],
  ["community", "Сообщество"],
]);

export function AdvancedStore({
  activeTab, onTab, sources, installed, catalogSkills, loading, refreshing,
  installedNames, installingName, searchQuery,
  onRefresh, onInstall, onUninstall, onPublish,
}: {
  activeTab: TabId;
  onTab: (tab: TabId) => void;
  sources: CatalogSource[];
  installed: InstalledSkill[];
  catalogSkills: CatalogSkill[];
  loading: boolean;
  refreshing: boolean;
  installedNames: Set<string>;
  installingName: string | null;
  searchQuery: string;
  onRefresh: () => void;
  onInstall: (skill: CatalogSkill) => void;
  onUninstall: (skill: InstalledSkill) => void;
  onPublish: (skill: InstalledSkill) => void;
}) {
  const tabs: { id: TabId; label: string; count?: number }[] = [
    { id: "installed", label: "Установленные", count: installed.length },
    ...sources.map((s) => ({ id: s.id as TabId, label: s.label })),
  ];

  const q = searchQuery.trim().toLowerCase();
  const filteredInstalled = q
    ? installed.filter(
        (s) => s.name.toLowerCase().includes(q) || s.description.toLowerCase().includes(q))
    : installed;

  return (
    <div>
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-white/40 uppercase tracking-wider">
          Источники каталога
        </span>
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="text-white/40 hover:text-white/80 transition disabled:opacity-50 ml-auto"
          title="Обновить каталог"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-6 bg-white/5 p-1.5 rounded-2xl w-fit border border-white/10">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTab(tab.id)}
            className={`px-4 py-2 text-xs tracking-wider uppercase font-medium transition-all duration-300 relative rounded-xl
              ${activeTab === tab.id ? "text-white" : "text-white/40 hover:text-white/80 hover:bg-white/5"}`}
          >
            <span className="relative z-10 flex items-center gap-1.5">
              {tab.label}
              {tab.count !== undefined && (
                <span className={`px-1.5 py-0.5 rounded-md text-[10px] ${activeTab === tab.id ? "bg-white/20" : "bg-black/30"}`}>
                  {tab.count}
                </span>
              )}
            </span>
            {activeTab === tab.id && (
              <div className="absolute inset-0 bg-gradient-to-r from-[var(--j-cyan)] to-[var(--j-purple)] rounded-xl opacity-80" />
            )}
          </button>
        ))}
      </div>

      <motion.div
        key={activeTab}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        {activeTab === "installed" ? (
          <InstalledList
            skills={filteredInstalled}
            onUninstall={onUninstall}
            onPublish={onPublish}
          />
        ) : (
          <CatalogList
            skills={catalogSkills}
            installedNames={installedNames}
            installingName={installingName}
            onInstall={onInstall}
            loading={loading}
            activeSource={sources.find((s) => s.id === activeTab)}
          />
        )}
      </motion.div>
    </div>
  );
}

function InstalledList({
  skills, onUninstall, onPublish,
}: {
  skills: InstalledSkill[];
  onUninstall: (skill: InstalledSkill) => void;
  onPublish: (skill: InstalledSkill) => void;
}) {
  if (skills.length === 0) {
    return (
      <div className="glass p-6 text-center text-sm text-white/30 rounded-2xl">
        Пока ничего не установлено. Выбери источник выше или вернись в витрину.
      </div>
    );
  }

  return (
    <div className="grid gap-2 stagger">
      {skills.map((skill) => (
        <div key={skill.name} className="glass glass-interactive p-5 flex items-center gap-4 relative overflow-hidden group rounded-2xl">
          <Sparkles className="w-5 h-5 text-[var(--j-green)] shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-base font-medium truncate">{skill.name}</span>
              <SourceBadge source={skill.source} />
            </div>
            <div className="text-sm text-white/50 truncate mt-1">{skill.description}</div>
            {skill.compatibility && (
              <div className="text-[11px] text-white/40 mt-1.5 flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-white/30" />
                {skill.compatibility}
              </div>
            )}
          </div>
          <button
            onClick={() => onPublish(skill)}
            className="text-white/30 hover:text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/10 transition p-2 rounded-lg"
            title="Опубликовать в каталог KALI"
          >
            <Upload className="w-4 h-4" />
          </button>
          {skill.source !== "builtin" && (
            <button
              onClick={() => onUninstall(skill)}
              className="text-white/30 hover:text-red-400 hover:bg-red-400/10 transition p-2 rounded-lg"
              title="Удалить"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          <span className="text-xs px-2.5 py-1 rounded bg-[var(--j-green)]/10 text-[var(--j-green)] shrink-0 border border-[var(--j-green)]/20">
            Активен
          </span>
        </div>
      ))}
    </div>
  );
}

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
      <div className="glass p-8 text-center rounded-2xl">
        <Loader2 className="w-5 h-5 text-[var(--j-cyan)] animate-spin mx-auto mb-2" />
        <div className="text-xs text-white/40">Загружаю каталог…</div>
      </div>
    );
  }

  if (skills.length === 0) {
    return (
      <div className="glass p-6 text-sm text-white/30 space-y-3 rounded-2xl">
        <div>
          Из источника <strong>{activeSource?.label}</strong> пока ничего не загружено.
        </div>
        <div className="text-xs">
          Нажми «Обновить» (справа сверху) — первая загрузка занимает несколько секунд.
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
          <div key={`${skill.source_id}/${skill.name}`} className="glass glass-interactive p-5 flex items-center gap-4 rounded-2xl">
            <TrustBadge trust={skill.trust} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-base font-medium truncate">{skill.name}</span>
                <span className="text-xs text-white/20">@{skill.repo_owner}</span>
                <a
                  href={skill.web_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-white/30 hover:text-white/60 shrink-0 ml-1"
                  title="Открыть на GitHub"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
              <div className="text-sm text-white/50 truncate mt-1">{skill.description}</div>
              {(skill.license || skill.compatibility) && (
                <div className="text-[11px] text-white/40 mt-1.5 flex gap-4">
                  {skill.license && (
                    <span className="flex items-center gap-1">
                      <Shield className="w-3 h-3 opacity-50" /> {skill.license}
                    </span>
                  )}
                  {skill.compatibility && <span>совместимость: {skill.compatibility}</span>}
                </div>
              )}
            </div>
            {installed ? (
              <span className="px-3 py-1.5 text-xs rounded-md bg-[var(--j-green)]/10 text-[var(--j-green)] flex items-center gap-1.5 shrink-0 border border-[var(--j-green)]/20">
                <Check className="w-3.5 h-3.5" />
                Установлено
              </span>
            ) : (
              <button
                disabled={isInstalling}
                onClick={() => onInstall(skill)}
                className="px-4 py-1.5 text-xs font-medium rounded-md bg-gradient-to-r from-[var(--j-cyan)]/20 to-[var(--j-cyan)]/10
                  text-[var(--j-cyan)] hover:from-[var(--j-cyan)]/30 hover:to-[var(--j-cyan)]/20
                  transition flex items-center gap-1.5 shrink-0 border border-[var(--j-cyan)]/30
                  disabled:opacity-50 disabled:cursor-wait"
              >
                {isInstalling ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
                {isInstalling ? "Устанавливаю…" : "Установить"}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TrustBadge({ trust }: { trust: string }) {
  const color = TRUST_COLORS.get(trust) ?? "var(--j-text-muted)";
  return (
    <span
      className="text-[10px] tracking-widest uppercase px-2 py-1 rounded-md shrink-0 flex items-center gap-1"
      style={{
        color,
        backgroundColor: color + "15",
        borderColor: color + "40",
        borderWidth: 1,
      }}
    >
      {TRUST_LABELS.get(trust) ?? trust}
    </span>
  );
}

function SourceBadge({ source }: { source: string }) {
  let label = source;
  let color = "var(--j-text-muted)";
  if (source === "builtin") { label = "встроенный"; color = "var(--j-cyan)"; }
  else if (source === "user") { label = "установлен"; color = "var(--j-green)"; }
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

export function PublishDialog({
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
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div className="glass p-6 max-w-lg w-full rounded-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 mb-4">
          <Upload className="w-5 h-5 text-[var(--j-cyan)]" />
          <h3 className="text-sm font-medium">Публикация «{state.skillName}»</h3>
          <button onClick={onClose} className="ml-auto text-white/30 hover:text-white/60">
            <X className="w-4 h-4" />
          </button>
        </div>

        {state.phase === "publishing" && (
          <div className="py-6 flex items-center gap-3 justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-[var(--j-cyan)]" />
            <span className="text-sm text-white/60">Проверяю и упаковываю навык…</span>
          </div>
        )}

        {state.phase === "error" && (
          <div className="space-y-3">
            <div className="flex items-start gap-2 text-sm text-red-400">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>Не получилось опубликовать — исправь и попробуй ещё раз</span>
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
              Пакет готов — остались шаги ниже
            </div>

            {state.warnings.length > 0 && (
              <div className="space-y-1">
                <div className="text-[10px] tracking-wider uppercase text-[var(--j-amber,#f59e0b)]">
                  Предупреждения
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
                <div className="text-[10px] tracking-wider uppercase text-white/40">Пакет</div>
                <div className="flex gap-2 items-center">
                  <code className="text-[11px] px-2 py-1.5 rounded bg-black/40 text-white/70 flex-1 truncate">
                    {state.bundlePath}
                  </code>
                  <button
                    onClick={copyBundlePath}
                    className="text-xs px-2 py-1.5 rounded bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] hover:bg-[var(--j-cyan)]/30"
                  >
                    Копировать
                  </button>
                </div>
              </div>
            )}

            <div className="space-y-1">
              <div className="text-[10px] tracking-wider uppercase text-white/40">Дальше</div>
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
                Открыть репозиторий каталога
              </a>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
