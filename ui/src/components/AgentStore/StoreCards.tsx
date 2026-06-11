import { Check, ExternalLink, KeyRound, Loader2, Settings as SettingsIcon, X } from "lucide-react";
import type { CuratedEntry } from "./curated";
import { useAppStore } from "../../stores/appStore";

export type CardState = "idle" | "busy" | "active";

/** Human storefront card: emoji + RU title + benefit + one obvious action. */
export function StoreCard({
  entry, state, onPrimary, onSetup,
}: {
  entry: CuratedEntry;
  state: CardState;
  onPrimary: (entry: CuratedEntry) => void;
  onSetup: (entry: CuratedEntry) => void;
}) {
  const activeLabel = entry.kind === "agent" ? "Работает" : "Установлено";
  const idleLabel = entry.kind === "agent" ? "Включить" : "Установить";

  return (
    <div className="glass glass-interactive p-5 flex items-center gap-4 rounded-2xl">
      <div className="text-3xl w-12 h-12 flex items-center justify-center rounded-xl bg-white/5 shrink-0">
        {entry.emoji}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-base font-medium truncate">{entry.title}</span>
          {entry.setup && (
            <button
              onClick={() => onSetup(entry)}
              className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md
                bg-[var(--j-amber,#f59e0b)]/10 text-[var(--j-amber,#f59e0b)]
                border border-[var(--j-amber,#f59e0b)]/30 hover:bg-[var(--j-amber,#f59e0b)]/20 transition"
              title="Что нужно настроить"
            >
              <KeyRound className="w-3 h-3" />
              нужен ключ
            </button>
          )}
        </div>
        <div className="text-sm text-white/50 mt-1">{entry.benefit}</div>
      </div>
      {state === "active" ? (
        <span className="px-3 py-1.5 text-xs rounded-lg bg-[var(--j-green)]/10 text-[var(--j-green)]
          flex items-center gap-1.5 shrink-0 border border-[var(--j-green)]/20">
          <Check className="w-3.5 h-3.5" />
          {activeLabel}
        </span>
      ) : (
        <button
          disabled={state === "busy"}
          onClick={() => onPrimary(entry)}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-gradient-to-r from-[var(--j-cyan)]/20 to-[var(--j-cyan)]/10
            text-[var(--j-cyan)] hover:from-[var(--j-cyan)]/30 hover:to-[var(--j-cyan)]/20
            transition flex items-center gap-1.5 shrink-0 border border-[var(--j-cyan)]/30
            disabled:opacity-50 disabled:cursor-wait"
        >
          {state === "busy" && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
          {state === "busy" ? "Секунду…" : idleLabel}
        </button>
      )}
    </div>
  );
}

/** Plain-language «нужен ключ» guidance: steps + where to get it + Settings. */
export function SetupDialog({
  entry, onClose,
}: {
  entry: CuratedEntry;
  onClose: () => void;
}) {
  if (!entry.setup) return null;
  const openSettings = () => {
    onClose();
    useAppStore.getState().setMode("settings");
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onClose}
    >
      <div
        className="glass p-6 max-w-md w-full rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-1">
          <span className="text-2xl">{entry.emoji}</span>
          <h3 className="text-base font-medium">{entry.title} — настройка</h3>
          <button onClick={onClose} className="ml-auto text-white/30 hover:text-white/60">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-white/60 mb-4">
          Чтобы всё заработало, нужен: <span className="text-white/90">{entry.setup.what}</span>.
          Это занимает пару минут:
        </p>
        <ol className="space-y-2 text-sm text-white/80 pl-5 list-decimal mb-5">
          {entry.setup.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>
        <div className="flex gap-2">
          {entry.setup.url && (
            <a
              href={entry.setup.url}
              target="_blank"
              rel="noreferrer"
              className="flex-1 px-3 py-2 text-sm rounded-lg bg-white/5 hover:bg-white/10 transition
                flex items-center justify-center gap-1.5 text-white/80 border border-white/10"
            >
              <ExternalLink className="w-3.5 h-3.5" />
              Где взять ключ
            </a>
          )}
          <button
            onClick={openSettings}
            className="flex-1 px-3 py-2 text-sm rounded-lg bg-[var(--j-cyan)]/20 hover:bg-[var(--j-cyan)]/30
              transition flex items-center justify-center gap-1.5 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30"
          >
            <SettingsIcon className="w-3.5 h-3.5" />
            Открыть настройки
          </button>
        </div>
      </div>
    </div>
  );
}
