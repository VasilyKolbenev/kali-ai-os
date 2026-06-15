import { useState } from "react";
import { Check, ExternalLink, KeyRound, Loader2, X } from "lucide-react";
import type { CuratedEntry } from "./curated";
import { api } from "../../api/client";

export type CardState = "idle" | "busy" | "active" | "needs-setup";

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
        <div className="text-base font-medium truncate">{entry.title}</div>
        <div className="text-sm text-white/50 mt-1">{entry.benefit}</div>
      </div>
      {state === "active" ? (
        <span className="px-3 py-1.5 text-xs rounded-lg bg-[var(--j-green)]/10 text-[var(--j-green)]
          flex items-center gap-1.5 shrink-0 border border-[var(--j-green)]/20">
          <Check className="w-3.5 h-3.5" />
          {activeLabel}
        </span>
      ) : state === "needs-setup" ? (
        <button
          onClick={() => onSetup(entry)}
          className="px-4 py-2 text-sm font-medium rounded-lg flex items-center gap-1.5 shrink-0
            bg-[var(--j-amber,#f59e0b)]/15 text-[var(--j-amber,#f59e0b)]
            border border-[var(--j-amber,#f59e0b)]/30 hover:bg-[var(--j-amber,#f59e0b)]/25 transition"
          title="Нужен ключ — нажми, чтобы настроить"
        >
          <KeyRound className="w-3.5 h-3.5" />
          Настроить
        </button>
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

/** Plain-language setup: steps, where to get the key, and inline fields to
    paste it — saved straight to settings, no trip to a separate screen. */
export function SetupDialog({
  entry, onClose, onSaved,
}: {
  entry: CuratedEntry;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const keys = entry.setup?.keys ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!entry.setup) return null;

  const canSave = keys.length > 0 && keys.every((k) => (values[k.env] || "").trim());

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, string> = {};
      for (const k of keys) payload[k.env] = values[k.env].trim();
      await api.updateSettings(payload);
      onSaved?.();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Не удалось сохранить");
    }
    setSaving(false);
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
        <ol className="space-y-2 text-sm text-white/80 pl-5 list-decimal mb-4">
          {entry.setup.steps.map((step, i) => (
            <li key={i}>{step}</li>
          ))}
        </ol>

        {entry.setup.url && (
          <a
            href={entry.setup.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs text-[var(--j-cyan)] hover:underline mb-4"
          >
            <ExternalLink className="w-3.5 h-3.5" />
            Где взять ключ
          </a>
        )}

        {keys.length > 0 ? (
          <div className="space-y-3">
            {keys.map((k) => (
              <div key={k.env}>
                <label className="block text-xs text-white/50 mb-1">{k.label}</label>
                <input
                  type="text"
                  value={values[k.env] || ""}
                  onChange={(e) => setValues((v) => ({ ...v, [k.env]: e.target.value }))}
                  placeholder="Вставь сюда"
                  className="w-full px-3 py-2 text-sm rounded-lg bg-black/40 border border-white/10
                    outline-none focus:border-[var(--j-cyan)]/40 text-white/90"
                />
              </div>
            ))}
            {error && <div className="text-xs text-red-400">{error}</div>}
            <button
              onClick={handleSave}
              disabled={!canSave || saving}
              className="w-full px-3 py-2.5 text-sm rounded-lg bg-[var(--j-cyan)]/20 hover:bg-[var(--j-cyan)]/30
                transition flex items-center justify-center gap-1.5 text-[var(--j-cyan)]
                border border-[var(--j-cyan)]/30 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {saving ? "Сохраняю…" : "Сохранить и включить"}
            </button>
          </div>
        ) : (
          <div className="text-xs text-white/40">
            Этот помощник подключается через вход в аккаунт. Следуй шагам выше.
          </div>
        )}
      </div>
    </div>
  );
}
