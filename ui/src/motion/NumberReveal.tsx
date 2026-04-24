import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion";

interface NumberRevealProps {
  value: number;
  durationMs?: number;
  format?: (n: number) => string;
  className?: string;
}

/**
 * Counts up from 0 to `value` over `durationMs`. Snaps to final value when
 * prefers-reduced-motion is set. Use in Dashboard tiles and status counters.
 */
export function NumberReveal({
  value,
  durationMs = 600,
  format = (n) => n.toLocaleString(),
  className,
}: NumberRevealProps) {
  const reduce = usePrefersReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);
  const raf = useRef<number | null>(null);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(Math.round(eased * value));
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current !== null) cancelAnimationFrame(raf.current);
    };
  }, [value, durationMs, reduce]);

  return (
    <span data-testid="number-reveal" className={className}>
      {format(display)}
    </span>
  );
}
