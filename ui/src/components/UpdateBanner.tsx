import { useUpdaterStore } from "../stores/updaterStore";

function gb(bytes: number): string {
  return (bytes / 1_000_000_000).toFixed(1).replace(".", ",");
}

/** Ненавязчивый баннер обновления (спека 2026-07-14-auto-update-design.md).
    Рендерится только в фазах available/downloading/ready/error и пока не dismissed. */
export function UpdateBanner() {
  const s = useUpdaterStore();
  // OPUS-202: fail-closed — never surface download/install when the updater is
  // disabled, even if a stale `available` lingers in the store.
  if (s.phase === "disabled") return null;
  if (s.dismissed || s.phase === "idle" || s.phase === "installing" || !s.available) return null;

  const pct = s.total > 0 ? Math.floor((s.downloaded / s.total) * 100) : 0;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border p-4 shadow-lg"
      style={{ background: "var(--j-surface, #111)", borderColor: "var(--j-border, #333)", color: "var(--j-text, #eee)" }}
      role="status"
    >
      {s.phase === "available" && (
        <>
          <div className="font-semibold">Доступна KALI {s.available.version}</div>
          {s.available.notes && (
            <div className="mt-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}>{s.available.notes}</div>
          )}
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.download()}>
              Скачать ({gb(s.total)} ГБ)
            </button>
            <button className="px-2 py-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}
              onClick={s.dismiss}>
              Позже
            </button>
          </div>
        </>
      )}
      {s.phase === "downloading" && (
        <>
          <div className="font-semibold">Скачивание KALI {s.available.version}… {pct} %</div>
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--j-border, #333)" }}>
            <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--j-accent, #2563eb)" }} />
          </div>
        </>
      )}
      {s.phase === "ready" && (
        <>
          <div className="font-semibold">KALI {s.available.version} готова к установке</div>
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.install()}>
              Перезапустить и обновить
            </button>
            <button className="px-2 py-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }} onClick={s.dismiss}>
              Позже
            </button>
          </div>
        </>
      )}
      {s.phase === "error" && (
        <>
          <div className="font-semibold">Обновление прервано</div>
          <div className="mt-1 text-sm" style={{ color: "var(--j-text-dim, #aaa)" }}>{s.error}</div>
          <div className="mt-2 flex items-center gap-2">
            <button className="rounded-lg px-3 py-1 text-sm font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void s.download()}>
              Продолжить
            </button>
            <a className="px-2 py-1 text-sm underline" style={{ color: "var(--j-text-dim, #aaa)" }}
              href="https://github.com/VasilyKolbenev/kali-ai-os/releases" target="_blank" rel="noreferrer">
              Скачать вручную
            </a>
          </div>
        </>
      )}
    </div>
  );
}
