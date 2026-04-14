import { useDashboardStore } from "../../../stores/dashboardStore";

export function WeatherWidget() {
  const data = useDashboardStore((s) => s.widgets.weather) as { temp_c?: number; condition?: string } | null;

  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>ПОГОДА</div>
      <div className="flex items-baseline gap-1">
        <span className="mono text-3xl font-light" style={{ color: "var(--j-cyan)" }}>
          {data?.temp_c != null ? `${Math.round(data.temp_c)}°` : "—"}
        </span>
        <span className="mono text-sm" style={{ color: "var(--j-text-dim)" }}>C</span>
      </div>
      <div className="mono text-[10px] mt-2" style={{ color: "var(--j-text-muted)" }}>
        {data?.condition ?? "Loading..."}
      </div>
    </div>
  );
}
