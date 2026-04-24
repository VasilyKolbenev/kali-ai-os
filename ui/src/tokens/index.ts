/**
 * Design token mirrors for use in TypeScript/JSX where var(--j-*) is awkward.
 * Values must stay in sync with tokens/*.css (enforced by tokens.test.ts).
 */
export const colors = {
  bg: "#050508",
  surface: "rgba(255, 255, 255, 0.03)",
  surfaceHover: "rgba(255, 255, 255, 0.06)",
  border: "rgba(255, 255, 255, 0.06)",
  borderGlow: "rgba(0, 212, 255, 0.15)",
  cyan: "#00d4ff",
  cyanDim: "rgba(0, 212, 255, 0.6)",
  cyanGlow: "rgba(0, 212, 255, 0.12)",
  cyanStrong: "rgba(0, 212, 255, 0.85)",
  cyanSoft: "rgba(0, 212, 255, 0.35)",
  cyanWash: "rgba(0, 212, 255, 0.05)",
  amber: "#ffb800",
  green: "#00e676",
  red: "#ff3d57",
  offline: "#4a5568",
  offlineGlow: "rgba(74, 85, 104, 0.2)",
  text: "#e8eaed",
  textDim: "rgba(255, 255, 255, 0.4)",
  textMuted: "rgba(255, 255, 255, 0.2)",
} as const;

export const motion = {
  durationFast: 150,
  durationBase: 300,
  durationSlow: 600,
  easeOut: [0.2, 0.8, 0.2, 1] as const,
  easeInOut: [0.4, 0, 0.2, 1] as const,
  easeExpo: [0.16, 1, 0.3, 1] as const,
} as const;

export type ColorToken = keyof typeof colors;
