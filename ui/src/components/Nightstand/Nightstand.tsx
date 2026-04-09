import { useState, useEffect } from "react";

export function Nightstand() {
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const interval = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  const hours = time.getHours().toString().padStart(2, "0");
  const minutes = time.getMinutes().toString().padStart(2, "0");
  const seconds = time.getSeconds().toString().padStart(2, "0");
  const isNight = time.getHours() >= 22 || time.getHours() < 6;

  return (
    <div className="flex flex-col items-center justify-center h-full gap-4">
      {/* Time */}
      <div className="flex items-baseline">
        <span className="mono text-8xl font-extralight tracking-tight glow-text" style={{ color: "var(--j-text)" }}>
          {hours}
        </span>
        <span className="mono text-8xl font-extralight breathe" style={{ color: "var(--j-cyan)" }}>:</span>
        <span className="mono text-8xl font-extralight tracking-tight glow-text" style={{ color: "var(--j-text)" }}>
          {minutes}
        </span>
        <span className="mono text-2xl font-light ml-2" style={{ color: "var(--j-text-muted)" }}>
          {seconds}
        </span>
      </div>

      {/* Date */}
      <div className="mono text-xs tracking-[6px] uppercase" style={{ color: "var(--j-text-muted)" }}>
        {time.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
      </div>

      {/* Night greeting */}
      {isNight && (
        <div className="mt-8 mono text-xs tracking-[3px] uppercase fade-in-up" style={{ color: "var(--j-cyan-dim)" }}>
          Sleep well
        </div>
      )}
    </div>
  );
}
