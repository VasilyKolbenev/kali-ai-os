import { useEffect, useState } from "react";
import { api } from "../../../api/client";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { HexFrame, HudDivider } from "../../hud";

interface VersionInfo {
  version?: string;
  build_profile?: string;
  commit?: string | null;
}

export function AdvancedSettings() {
  const [version, setVersion] = useState<VersionInfo | null>(null);
  const [resetMessage, setResetMessage] = useState<string | null>(null);
  const onboardingReset = useOnboardingStore((s) => s.reset);

  useEffect(() => {
    fetch("http://127.0.0.1:3006/version")
      .then((r) => r.json())
      .then(setVersion)
      .catch(() => setVersion(null));
  }, []);

  async function replayOnboarding() {
    setResetMessage("Сбрасываю...");
    try {
      await api.updateSettings({ onboarding_completed: false });
    } catch {
      /* non-fatal — store flip below still triggers the gate */
    }
    onboardingReset();
    setResetMessage("Готово. Onboarding запустится сейчас.");
    setTimeout(() => window.location.reload(), 600);
  }

  return (
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="ПРОДВИНУТЫЕ" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div
          style={{
            padding: "var(--j-space-4)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--j-space-3)",
            fontSize: "var(--j-text-xs)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--j-text-dim)" }}>Version</span>
            <span style={{ fontFamily: "var(--j-font-mono)", color: "var(--j-text)" }}>
              {version?.version ?? "…"}
            </span>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: "var(--j-text-dim)" }}>Build</span>
            <span style={{ fontFamily: "var(--j-font-mono)", color: "var(--j-text)" }}>
              {version?.build_profile ?? "…"}
              {version?.commit ? ` · ${version.commit}` : ""}
            </span>
          </div>

          <div
            style={{
              marginTop: "var(--j-space-3)",
              display: "flex",
              flexDirection: "column",
              gap: "var(--j-space-2)",
            }}
          >
            <button
              onClick={replayOnboarding}
              style={{
                alignSelf: "flex-start",
                padding: "var(--j-space-2) var(--j-space-4)",
                background: "color-mix(in srgb, var(--j-cyan) 10%, transparent)",
                border: "1px solid var(--j-border-glow)",
                borderRadius: "var(--j-radius-md)",
                color: "var(--j-cyan)",
                fontFamily: "var(--j-font-mono)",
                fontSize: "var(--j-text-xs)",
                letterSpacing: "var(--j-tracking-wide)",
                textTransform: "uppercase",
                cursor: "pointer",
                transition: "background var(--j-duration-base) var(--j-ease-in-out)",
              }}
            >
              Прогнать onboarding заново
            </button>
            {resetMessage && (
              <span style={{ color: "var(--j-text-dim)" }}>{resetMessage}</span>
            )}
          </div>
        </div>
      </HexFrame>
    </div>
  );
}
