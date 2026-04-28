import { useDashboardStore } from "../../../stores/dashboardStore";

export function TasksWidget() {
  const data = useDashboardStore((s) => s.widgets.tasks) as { done: number; total: number } | null;
  const pct = data && data.total > 0 ? Math.round((data.done / data.total) * 100) : 0;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>ЗАДАЧИ</div>
      <div className="flex items-baseline gap-1">
        <span className="mono text-3xl font-light" style={{ color: "var(--j-green)" }}>{data?.done ?? "—"}</span>
        <span className="mono text-sm" style={{ color: "var(--j-text-muted)" }}>{data ? `/${data.total}` : ""}</span>
      </div>
      <div className="mt-3 h-[2px] rounded-full overflow-hidden" style={{ background: "var(--j-border)" }}>
        <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: "var(--j-green)", boxShadow: "0 0 8px var(--j-success-glow)" }} />
      </div>
    </div>
  );
}
