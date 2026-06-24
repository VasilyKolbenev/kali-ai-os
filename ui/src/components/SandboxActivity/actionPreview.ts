export type PreviewRisk = "high" | "med" | "low";

export interface ActionPreview {
  label: string;
  risk: PreviewRisk;
}

/**
 * Parse the dry-run preview (plain-language label + risk tier) that the sandbox
 * backend attaches to an audit record's `extra` JSON. Disclosure only — this
 * just makes the Activity view human-readable. Returns null when the payload is
 * missing, malformed, or lacks valid preview fields.
 */
export function parseActionPreview(extra: string | null): ActionPreview | null {
  if (!extra) return null;
  try {
    const parsed = JSON.parse(extra) as Record<string, unknown>;
    const label = parsed.preview_label;
    const risk = parsed.preview_risk;
    if (
      typeof label === "string" &&
      (risk === "high" || risk === "med" || risk === "low")
    ) {
      return { label, risk };
    }
    return null;
  } catch {
    return null;
  }
}

/** Risk-tier display: tag/border colour + a short plain-language tag. Shared by
 *  the Dashboard activity widget and the standalone Activity view. */
export const RISK_COLOR: Record<PreviewRisk, string> = {
  high: "var(--j-red, #ef4444)",
  med: "var(--j-amber, #f59e0b)",
  low: "var(--j-text-muted, rgba(255,255,255,0.45))",
};
export const RISK_TAG: Record<PreviewRisk, string> = {
  high: "важно",
  med: "личное",
  low: "",
};
