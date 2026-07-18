import type { StartupView } from "../../lib/startupState";

/** Оверлей ТОЛЬКО для degraded (янтарь) / failed (красный); иначе null. */
export function StartupSurface({ view }: { view: StartupView }) {
  if (view.kind !== "degraded" && view.kind !== "failed") return null;
  const failed = view.kind === "failed";
  const color = failed ? "var(--j-red, #ef4444)" : "var(--j-amber, #f59e0b)";
  return (
    <div
      role="alert"
      data-testid={`startup-${view.kind}`}
      className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-3 text-center px-8"
      style={{ background: "var(--j-bg)", color: "var(--j-text-dim)" }}
    >
      <div className="text-lg font-semibold" style={{ color }}>
        {view.title}
      </div>
      <div className="text-sm max-w-md" style={{ color: "var(--j-text-muted)" }}>
        {view.body}
      </div>
    </div>
  );
}
