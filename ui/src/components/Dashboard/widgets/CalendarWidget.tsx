import { useDashboardStore } from "../../../stores/dashboardStore";

export function CalendarWidget() {
  const data = useDashboardStore((s) => s.widgets.calendar) as { next: string; time: string } | undefined;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>СОБЫТИЕ</div>
      <div className="text-base font-medium" style={{ color: "var(--j-text)" }}>{data?.next ?? "Нет событий"}</div>
      <div className="mono text-xs mt-1" style={{ color: "var(--j-cyan-dim)" }}>{data?.time ?? ""}</div>
    </div>
  );
}
