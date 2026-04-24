import { useEffect, useState } from "react";
import { api } from "../../../api/client";
import { useOnboardingStore } from "../../../stores/onboardingStore";

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
    <div className="glass p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-sm font-medium">Продвинутые</span>
      </div>

      <div className="flex flex-col gap-3 text-xs">
        <div className="flex justify-between">
          <span className="text-white/40">Version</span>
          <span className="mono text-white/70">{version?.version ?? "…"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">Build</span>
          <span className="mono text-white/70">
            {version?.build_profile ?? "…"}
            {version?.commit ? ` · ${version.commit}` : ""}
          </span>
        </div>

        <div className="mt-3 flex flex-col gap-2">
          <button
            onClick={replayOnboarding}
            className="self-start px-4 py-2 rounded text-xs transition hover:bg-white/5"
            style={{
              background: "color-mix(in srgb, var(--j-cyan) 10%, transparent)",
              border: "1px solid var(--j-border-glow)",
              color: "var(--j-cyan)",
              fontFamily: "var(--j-font-mono)",
              letterSpacing: "var(--j-tracking-wide)",
              textTransform: "uppercase",
            }}
          >
            Прогнать onboarding заново
          </button>
          {resetMessage && (
            <span className="text-white/50">{resetMessage}</span>
          )}
        </div>
      </div>
    </div>
  );
}
