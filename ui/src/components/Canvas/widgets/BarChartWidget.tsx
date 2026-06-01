import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

interface BarItem {
  label: string;
  value: number;
  color?: string;
}

export function BarChartWidget({ widget }: Props) {
  const items = (widget.data.items as BarItem[] | undefined) ?? [];
  const maxValue = Math.max(...items.map((i) => i.value), 1);

  const palette = [
    "var(--j-cyan)",
    "var(--j-purple)",
    "var(--j-green)",
    "var(--j-amber)",
    "var(--j-red)",
    "var(--j-blue)",
  ];

  return (
    <div className="glass p-5 flex flex-col gap-3">
      <div
        className="mono text-[10px] tracking-[2px] uppercase"
        style={{ color: "var(--j-text-muted)" }}
      >
        {widget.title}
      </div>
      <div className="flex flex-col gap-2">
        {items.map((item, i) => {
          const pct = (item.value / maxValue) * 100;
          const barColor = item.color || palette[i % palette.length];
          return (
            <div key={item.label} className="flex flex-col gap-1">
              <div className="flex justify-between items-baseline">
                <span className="mono text-xs" style={{ color: "var(--j-text-dim)" }}>
                  {item.label}
                </span>
                <span className="mono text-xs font-semibold" style={{ color: barColor }}>
                  {item.value}
                </span>
              </div>
              <div
                className="w-full h-2 rounded-full overflow-hidden"
                style={{ background: "var(--j-surface)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${pct}%`,
                    background: `linear-gradient(90deg, ${barColor}, color-mix(in srgb, ${barColor} 60%, transparent))`,
                    transition: "width 0.8s cubic-bezier(0.22, 1, 0.36, 1)",
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
