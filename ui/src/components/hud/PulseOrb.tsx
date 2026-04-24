import { usePrefersReducedMotion } from "../../motion/usePrefersReducedMotion";

type Status = "info" | "success" | "warning" | "danger";

interface PulseOrbProps {
  active?: boolean;
  status?: Status;
  size?: number;
  className?: string;
}

const STATUS_COLORS: Record<Status, { core: string; glow: string }> = {
  info: { core: "var(--j-cyan)", glow: "var(--j-cyan-glow)" },
  success: { core: "var(--j-success)", glow: "var(--j-success-glow)" },
  warning: { core: "var(--j-warning)", glow: "var(--j-warning-glow)" },
  danger: { core: "var(--j-danger)", glow: "var(--j-danger-glow)" },
};

/**
 * Small pulsing reactor-style indicator. Shrunk version of ArcReactor's core.
 * Use anywhere you need "something is happening here" — status bar, nightstand,
 * voice-mode entry point. `active` drives whether it pulses or dims.
 */
export function PulseOrb({
  active = true,
  status = "info",
  size = 12,
  className,
}: PulseOrbProps) {
  const reduce = usePrefersReducedMotion();
  const colors = active ? STATUS_COLORS[status] : { core: "var(--j-offline)", glow: "var(--j-offline-glow)" };
  return (
    <span
      data-testid="pulse-orb"
      data-state={active ? "active" : "offline"}
      data-status={status}
      className={className}
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${colors.core} 0%, ${colors.core}44 60%, transparent 100%)`,
        boxShadow: active ? `0 0 ${size}px ${colors.glow}` : "none",
        animation: active && !reduce ? "pulse-orb 2s ease-in-out infinite" : "none",
      }}
    />
  );
}
