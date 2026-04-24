import { HexFrame, HudDivider, PulseOrb, ScanLineBg } from "../hud";
import { FadeSlideUp, GlowPulse, NumberReveal, ScaleHover } from "../../motion";
import { colors } from "../../tokens";

export function Showcase() {
  return (
    <div style={{ padding: "var(--j-space-8)", overflowY: "auto", width: "100%", height: "100%" }}>
      <h1 style={{ fontFamily: "var(--j-font-mono)", letterSpacing: "var(--j-tracking-hud)", color: "var(--j-cyan)" }}>
        ИНТЕРФЕЙС — SHOWCASE
      </h1>

      <HudDivider label="Colors" />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "var(--j-space-3)", margin: "var(--j-space-4) 0" }}>
        {Object.entries(colors).map(([name, value]) => (
          <div key={name} style={{ background: value, padding: "var(--j-space-3)", borderRadius: "var(--j-radius-md)", fontSize: "var(--j-text-xs)" }}>
            <code style={{ mixBlendMode: "difference", color: "white" }}>{name}</code>
          </div>
        ))}
      </div>

      <HudDivider label="Motion" />
      <div style={{ display: "flex", gap: "var(--j-space-4)", flexWrap: "wrap", margin: "var(--j-space-4) 0" }}>
        <FadeSlideUp><HexFrame><div style={{ padding: "var(--j-space-4)" }}>FadeSlideUp</div></HexFrame></FadeSlideUp>
        <ScaleHover><HexFrame><div style={{ padding: "var(--j-space-4)" }}>ScaleHover (hover me)</div></HexFrame></ScaleHover>
        <GlowPulse><HexFrame active><div style={{ padding: "var(--j-space-4)" }}>GlowPulse</div></HexFrame></GlowPulse>
        <div style={{ padding: "var(--j-space-4)", border: "1px solid var(--j-border)", borderRadius: "var(--j-radius-md)" }}>
          <NumberReveal value={42} /> agents
        </div>
      </div>

      <HudDivider label="HUD Primitives" />
      <div style={{ display: "flex", gap: "var(--j-space-4)", alignItems: "center", margin: "var(--j-space-4) 0" }}>
        <PulseOrb /> info
        <PulseOrb status="success" /> success
        <PulseOrb status="warning" /> warning
        <PulseOrb status="danger" /> danger
        <PulseOrb active={false} /> offline
      </div>

      <div style={{ position: "relative", height: 120, border: "1px solid var(--j-border)", borderRadius: "var(--j-radius-md)", overflow: "hidden", margin: "var(--j-space-4) 0" }}>
        <ScanLineBg />
        <div style={{ padding: "var(--j-space-4)" }}>ScanLineBg overlay demo</div>
      </div>
    </div>
  );
}
