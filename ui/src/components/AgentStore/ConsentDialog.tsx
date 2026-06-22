import { AlertTriangle, ShieldCheck, X } from "lucide-react";
import type { CuratedEntry } from "./curated";
import type { AgentCapability } from "../../api/types";

/**
 * Plain-language permission disclosure shown before enabling an agent that
 * touches personal data (sends/writes/reads). Disclosure only — «Разрешить»
 * runs the SAME enable path the one-click cards already use; «Не сейчас»
 * cancels. The local-trust line is the moat: consent stays on-device, no
 * accounts, no external calls.
 */
export function ConsentDialog({
  entry, capabilities, onAllow, onCancel,
}: {
  entry: CuratedEntry;
  capabilities: AgentCapability[];
  onAllow: () => void;
  onCancel: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
      onClick={onCancel}
    >
      <div
        className="glass p-6 max-w-md w-full rounded-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-1">
          <span className="text-2xl">{entry.emoji}</span>
          <h3 className="text-base font-medium">{entry.title} — доступ</h3>
          <button onClick={onCancel} className="ml-auto text-white/30 hover:text-white/60">
            <X className="w-4 h-4" />
          </button>
        </div>
        <p className="text-sm text-white/60 mb-4">
          Чтобы помогать, «{entry.title}» сможет:
        </p>

        <ul className="space-y-2 text-sm mb-4">
          {capabilities.map((cap) =>
            cap.risk === "high" ? (
              <li key={cap.id} className="flex items-start gap-2 font-medium text-white/90">
                <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-[var(--j-amber,#f59e0b)]" />
                <span>{cap.label}</span>
              </li>
            ) : (
              <li key={cap.id} className="flex items-start gap-2 text-white/70">
                <span className="w-1 h-1 mt-2 shrink-0 rounded-full bg-white/30" />
                <span>{cap.label}</span>
              </li>
            ),
          )}
        </ul>

        <div className="flex items-center gap-2 text-xs text-white/50 mb-5">
          <ShieldCheck className="w-3.5 h-3.5 shrink-0 text-[var(--j-green)]" />
          Это решение остаётся на твоём устройстве
        </div>

        <div className="flex gap-2">
          <button
            onClick={onCancel}
            className="flex-1 px-3 py-2.5 text-sm rounded-lg bg-white/5 hover:bg-white/10
              transition text-white/70 border border-white/10"
          >
            Не сейчас
          </button>
          <button
            onClick={onAllow}
            className="flex-1 px-3 py-2.5 text-sm rounded-lg bg-[var(--j-cyan)]/20 hover:bg-[var(--j-cyan)]/30
              transition flex items-center justify-center gap-1.5 text-[var(--j-cyan)]
              border border-[var(--j-cyan)]/30"
          >
            <ShieldCheck className="w-4 h-4" />
            Разрешить
          </button>
        </div>
      </div>
    </div>
  );
}
