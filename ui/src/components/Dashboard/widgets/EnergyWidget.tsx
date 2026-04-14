import { useDashboardStore } from "../../../stores/dashboardStore";

export function EnergyWidget() {
  const data = useDashboardStore((s) => s.widgets.energy) as { calories: number } | undefined;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>ЭНЕРГИЯ</div>
      <div className="flex items-baseline gap-1">
        <span className="mono text-3xl font-light" style={{ color: "var(--j-red)" }}>{data?.calories?.toLocaleString() ?? "\u2014"}</span>
        <span className="mono text-[10px]" style={{ color: "var(--j-text-muted)" }}>kcal</span>
      </div>
    </div>
  );
}
