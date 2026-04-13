import { useDashboardStore } from "../../../stores/dashboardStore";

export function SpendingWidget() {
  const data = useDashboardStore((s) => s.widgets.spending) as { amount: number; currency: string } | undefined;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>Spent</div>
      <div className="flex items-baseline gap-0.5">
        <span className="mono text-sm" style={{ color: "var(--j-amber)" }}>{data?.currency ?? ""}</span>
        <span className="mono text-3xl font-light" style={{ color: "var(--j-amber)" }}>{data?.amount ?? "—"}</span>
      </div>
    </div>
  );
}
