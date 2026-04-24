interface HudDividerProps {
  label?: string;
  className?: string;
}

/**
 * Horizontal rule with glow + optional ALL-CAPS label in the middle.
 * Used to divide Dashboard sections and Settings groups.
 */
export function HudDivider({ label, className }: HudDividerProps) {
  const lineStyle = {
    flex: 1,
    height: 1,
    background: "linear-gradient(90deg, transparent, var(--j-border-glow), transparent)",
  };
  return (
    <div
      data-hud="hud-divider"
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--j-space-3)",
        width: "100%",
      }}
    >
      <span style={lineStyle} />
      {label !== undefined && (
        <span
          style={{
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-hud)",
            color: "var(--j-text-dim)",
            textTransform: "uppercase",
            whiteSpace: "nowrap",
          }}
        >
          {label}
        </span>
      )}
      <span style={lineStyle} />
    </div>
  );
}
