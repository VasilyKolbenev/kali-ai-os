import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

export function StatCardWidget({ widget }: Props) {
  const { data } = widget;
  const value = String(data.value ?? "—");
  const subtitle = String(data.subtitle ?? "");
  const trend = data.trend as string | undefined;
  const trendValue = String(data.trend_value ?? "");
  const icon = String(data.icon ?? "📊");

  const trendColor =
    trend === "up" ? "var(--j-green)" : trend === "down" ? "var(--j-red)" : "var(--j-text-muted)";
  const trendArrow = trend === "up" ? "↑" : trend === "down" ? "↓" : "";

  return (
    <div className="glass p-5 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xl">{icon}</span>
        <span
          className="mono text-[10px] tracking-[2px] uppercase"
          style={{ color: "var(--j-text-muted)" }}
        >
          {widget.title}
        </span>
      </div>
      <div className="mono text-3xl font-light" style={{ color: "var(--j-cyan)" }}>
        {value}
      </div>
      <div className="flex items-center gap-2">
        {trendArrow && (
          <span className="mono text-xs font-semibold" style={{ color: trendColor }}>
            {trendArrow} {trendValue}
          </span>
        )}
        {subtitle && (
          <span className="mono text-[10px]" style={{ color: "var(--j-text-muted)" }}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
