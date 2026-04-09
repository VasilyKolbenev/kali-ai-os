import { useDashboardStore } from "../../../stores/dashboardStore";

export function SleepWidget() {
  const data = useDashboardStore((s) => s.widgets.sleep) as { hours: number; hrv: number } | undefined;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>Sleep</div>
      <div className="flex items-baseline gap-1">
        <span className="mono text-3xl font-light glow-text" style={{ color: "var(--j-cyan)" }}>{data?.hours ?? "\u2014"}</span>
        <span className="mono text-sm" style={{ color: "var(--j-text-dim)" }}>h</span>
      </div>
      <div className="mono text-[10px] mt-2" style={{ color: "var(--j-text-muted)" }}>HRV {data?.hrv ?? "\u2014"}</div>
    </div>
  );
}
