import type { CanvasWidget } from "../../../stores/canvasStore";

interface Props {
  widget: CanvasWidget;
}

export function ProgressWidget({ widget }: Props) {
  const value = Number(widget.data.value ?? 0);
  const max = Number(widget.data.max ?? 100);
  const label = String(widget.data.label ?? "");
  const color = String(widget.data.color ?? "var(--j-cyan)");
  const pct = Math.min(Math.max((value / max) * 100, 0), 100);

  const R = 52;
  const stroke = 8;
  const circumference = 2 * Math.PI * R;
  const dashOffset = circumference - (pct / 100) * circumference;

  return (
    <div className="glass p-5 flex flex-col items-center gap-3">
      <div
        className="mono text-[10px] tracking-[2px] uppercase"
        style={{ color: "var(--j-text-muted)" }}
      >
        {widget.title}
      </div>
      <div className="relative" style={{ width: 128, height: 128 }}>
        <svg viewBox="0 0 128 128" className="w-full h-full" style={{ transform: "rotate(-90deg)" }}>
          {/* Background ring */}
          <circle
            cx={64}
            cy={64}
            r={R}
            fill="none"
            stroke="var(--j-surface)"
            strokeWidth={stroke}
          />
          {/* Progress ring */}
          <circle
            cx={64}
            cy={64}
            r={R}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{
              transition: "stroke-dashoffset 1s cubic-bezier(0.22, 1, 0.36, 1)",
              filter: `drop-shadow(0 0 6px ${color})`,
            }}
          />
        </svg>
        <div
          className="absolute inset-0 flex flex-col items-center justify-center"
        >
          <span className="mono text-2xl font-light" style={{ color }}>
            {Math.round(pct)}%
          </span>
        </div>
      </div>
      <div className="flex flex-col items-center gap-0.5">
        <span className="mono text-xs" style={{ color: "var(--j-text-dim)" }}>
          {value} / {max}
        </span>
        {label && (
          <span className="mono text-[10px]" style={{ color: "var(--j-text-muted)" }}>
            {label}
          </span>
        )}
      </div>
    </div>
  );
}
