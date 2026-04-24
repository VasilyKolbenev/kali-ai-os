import type { ReactNode } from "react";

interface HexFrameProps {
  children: ReactNode;
  active?: boolean;
  className?: string;
}

/**
 * Hex-clipped container. Used for primary-action cards, agent tiles, hero
 * frames. Active state adds a cyan glow border. Corners carved via clip-path.
 */
export function HexFrame({ children, active = false, className }: HexFrameProps) {
  const corner = "14px";
  return (
    <div
      data-hud="hex-frame"
      data-active={active}
      className={className}
      style={{
        clipPath: `polygon(
          ${corner} 0,
          calc(100% - ${corner}) 0,
          100% ${corner},
          100% calc(100% - ${corner}),
          calc(100% - ${corner}) 100%,
          ${corner} 100%,
          0 calc(100% - ${corner}),
          0 ${corner}
        )`,
        background: active ? "var(--j-surface-hover)" : "var(--j-surface)",
        border: `1px solid ${active ? "var(--j-border-glow)" : "var(--j-border)"}`,
        boxShadow: active ? "var(--j-elev-2)" : "var(--j-elev-0)",
        transition: "all var(--j-duration-base) var(--j-ease-in-out)",
      }}
    >
      {children}
    </div>
  );
}
