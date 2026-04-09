import { useVoiceStore } from "../../stores/voiceStore";

const STATE_COLORS: Record<string, { core: string; glow: string; speed: number }> = {
  idle: { core: "#00d4ff", glow: "rgba(0, 212, 255, 0.3)", speed: 1 },
  listening: { core: "#00d4ff", glow: "rgba(0, 212, 255, 0.5)", speed: 2.5 },
  thinking: { core: "#ffb800", glow: "rgba(255, 184, 0, 0.4)", speed: 4 },
  speaking: { core: "#00e676", glow: "rgba(0, 230, 118, 0.4)", speed: 1.5 },
};

export function ArcReactor() {
  const voiceState = useVoiceStore((s) => s.state);
  const config = STATE_COLORS[voiceState] ?? STATE_COLORS.idle;

  return (
    <div className="relative w-72 h-72 flex items-center justify-center">
      {/* Outermost glow */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background: `radial-gradient(circle, ${config.glow} 0%, transparent 70%)`,
          filter: "blur(30px)",
          transition: "all 0.8s ease",
        }}
      />

      {/* Outer ring segments */}
      <svg className="absolute w-full h-full" viewBox="0 0 300 300" style={{ animation: `spin ${20 / config.speed}s linear infinite` }}>
        {Array.from({ length: 12 }).map((_, i) => {
          const angle = i * 30;
          const gap = 4;
          return (
            <path
              key={i}
              d={describeArc(150, 150, 130, angle + gap, angle + 30 - gap)}
              fill="none"
              stroke={config.core}
              strokeWidth="3"
              opacity={0.3 + (i % 3) * 0.15}
              style={{ filter: `drop-shadow(0 0 4px ${config.glow})`, transition: "all 0.5s ease" }}
            />
          );
        })}
      </svg>

      {/* Middle ring */}
      <svg className="absolute w-full h-full" viewBox="0 0 300 300" style={{ animation: `spin-reverse ${15 / config.speed}s linear infinite` }}>
        {Array.from({ length: 8 }).map((_, i) => {
          const angle = i * 45;
          return (
            <path
              key={i}
              d={describeArc(150, 150, 100, angle + 5, angle + 40)}
              fill="none"
              stroke={config.core}
              strokeWidth="2.5"
              opacity={0.4}
              style={{ filter: `drop-shadow(0 0 6px ${config.glow})`, transition: "all 0.5s ease" }}
            />
          );
        })}
      </svg>

      {/* Inner ring */}
      <svg className="absolute w-full h-full" viewBox="0 0 300 300" style={{ animation: `spin ${10 / config.speed}s linear infinite` }}>
        <circle cx="150" cy="150" r="70" fill="none" stroke={config.core} strokeWidth="1.5" opacity="0.3"
          style={{ filter: `drop-shadow(0 0 4px ${config.glow})`, transition: "all 0.5s ease" }} />
        {Array.from({ length: 6 }).map((_, i) => {
          const angle = i * 60;
          return (
            <path
              key={i}
              d={describeArc(150, 150, 70, angle + 5, angle + 50)}
              fill="none"
              stroke={config.core}
              strokeWidth="2"
              opacity={0.5}
              style={{ filter: `drop-shadow(0 0 8px ${config.glow})`, transition: "all 0.5s ease" }}
            />
          );
        })}
      </svg>

      {/* Core circle */}
      <div
        className="relative w-20 h-20 rounded-full flex items-center justify-center"
        style={{
          background: `radial-gradient(circle, ${config.core}22 0%, transparent 70%)`,
          boxShadow: `0 0 30px ${config.glow}, 0 0 60px ${config.glow}, inset 0 0 20px ${config.glow}`,
          border: `2px solid ${config.core}55`,
          transition: "all 0.8s ease",
        }}
      >
        {/* Inner core dot */}
        <div
          className="w-8 h-8 rounded-full"
          style={{
            background: `radial-gradient(circle, ${config.core} 0%, ${config.core}44 60%, transparent 100%)`,
            boxShadow: `0 0 15px ${config.core}, 0 0 30px ${config.glow}`,
            transition: "all 0.5s ease",
            animation: voiceState === "idle" ? "breathe-core 4s ease-in-out infinite" : "none",
          }}
        />
      </div>

      {/* Tick marks around outer ring */}
      <svg className="absolute w-full h-full" viewBox="0 0 300 300">
        {Array.from({ length: 60 }).map((_, i) => {
          const angle = (i * 6 * Math.PI) / 180;
          const r1 = i % 5 === 0 ? 138 : 140;
          const r2 = 145;
          const x1 = 150 + r1 * Math.cos(angle);
          const y1 = 150 + r1 * Math.sin(angle);
          const x2 = 150 + r2 * Math.cos(angle);
          const y2 = 150 + r2 * Math.sin(angle);
          return (
            <line
              key={i}
              x1={x1} y1={y1} x2={x2} y2={y2}
              stroke={config.core}
              strokeWidth={i % 5 === 0 ? "1.5" : "0.5"}
              opacity={i % 5 === 0 ? 0.4 : 0.15}
              style={{ transition: "all 0.5s ease" }}
            />
          );
        })}
      </svg>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes spin-reverse { from { transform: rotate(360deg); } to { transform: rotate(0deg); } }
        @keyframes breathe-core {
          0%, 100% { transform: scale(1); opacity: 0.8; }
          50% { transform: scale(1.1); opacity: 1; }
        }
      `}</style>
    </div>
  );
}

// SVG arc path helper
function describeArc(cx: number, cy: number, r: number, startAngle: number, endAngle: number): string {
  const start = polarToCartesian(cx, cy, r, endAngle);
  const end = polarToCartesian(cx, cy, r, startAngle);
  const largeArc = endAngle - startAngle <= 180 ? "0" : "1";
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
}

function polarToCartesian(cx: number, cy: number, r: number, angle: number) {
  const rad = ((angle - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}
