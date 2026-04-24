interface ScanLineBgProps {
  opacity?: number;
  className?: string;
}

/**
 * Subtle horizontal scan-line overlay — CRT-reminiscent atmosphere.
 * Place as first child of a relatively-positioned container.
 */
export function ScanLineBg({ opacity = 0.03, className }: ScanLineBgProps) {
  return (
    <div
      data-hud="scan-line-bg"
      className={className}
      aria-hidden="true"
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        backgroundImage:
          "repeating-linear-gradient(0deg, rgba(255,255,255,0.6) 0, rgba(255,255,255,0.6) 1px, transparent 1px, transparent 3px)",
        opacity,
        mixBlendMode: "overlay",
      }}
    />
  );
}
