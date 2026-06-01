import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

interface DataPoint {
  label?: string;
  value: number;
}

export function LineChartWidget({ widget }: Props) {
  const points = (widget.data.points as DataPoint[] | undefined) ?? [];
  const color = String(widget.data.color ?? "var(--j-cyan)");

  if (points.length < 2) {
    return (
      <div className="glass p-5">
        <div
          className="mono text-[10px] tracking-[2px] uppercase mb-3"
          style={{ color: "var(--j-text-muted)" }}
        >
          {widget.title}
        </div>
        <div className="mono text-xs" style={{ color: "var(--j-text-dim)" }}>
          Нужно минимум 2 точки данных
        </div>
      </div>
    );
  }

  const values = points.map((p) => p.value);
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const W = 300;
  const H = 120;
  const padX = 8;
  const padY = 12;
  const chartW = W - padX * 2;
  const chartH = H - padY * 2;

  const coords = points.map((p, i) => ({
    x: padX + (i / (points.length - 1)) * chartW,
    y: padY + chartH - ((p.value - minVal) / range) * chartH,
  }));

  const pathD = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x} ${c.y}`).join(" ");
  const areaD = `${pathD} L ${coords[coords.length - 1].x} ${H} L ${coords[0].x} ${H} Z`;

  const gradId = `grad-${widget.id}`;

  return (
    <div className="glass p-5 flex flex-col gap-2">
      <div
        className="mono text-[10px] tracking-[2px] uppercase"
        style={{ color: "var(--j-text-muted)" }}
      >
        {widget.title}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 140 }}>
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <path d={areaD} fill={`url(#${gradId})`} />
        <path d={pathD} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        {coords.map((c, i) => (
          <circle key={i} cx={c.x} cy={c.y} r={3} fill={color} opacity={0.8} />
        ))}
      </svg>
      {points[0]?.label && (
        <div className="flex justify-between">
          <span className="mono text-[9px]" style={{ color: "var(--j-text-muted)" }}>
            {points[0].label}
          </span>
          <span className="mono text-[9px]" style={{ color: "var(--j-text-muted)" }}>
            {points[points.length - 1].label}
          </span>
        </div>
      )}
    </div>
  );
}
