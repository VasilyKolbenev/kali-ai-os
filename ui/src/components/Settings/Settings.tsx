import { useEffect, useState } from "react";
import { Settings as SettingsIcon, Save } from "lucide-react";
import { api } from "../../api/client";
import { LlmSettings, type LlmSettingsValue } from "./sections/LlmSettings";
import { AdvancedSettings } from "./sections/AdvancedSettings";
import { HexFrame, HudDivider } from "../hud";

interface SettingsData {
  llm: LlmSettingsValue;
  tts: { enabled: boolean; pitch_shift: number; speaker: string };
  voice: { wake_word: string; mode: string; stt_model: string };
  language: string;
}

const LANGUAGES = [
  { id: "ru", label: "Русский" },
  { id: "en", label: "English" },
  { id: "zh", label: "中文" },
];

function emptySettings(): SettingsData {
  return {
    llm: {
      provider: "openai",
      openai_key: "",
      openai_model: "gpt-5.4-mini",
      anthropic_key: "",
      anthropic_model: "claude-sonnet-4-20250514",
      google_key: "",
      google_model: "gemini-3.1-pro",
      deepseek_key: "",
      deepseek_model: "deepseek-v3.2",
    },
    tts: { enabled: true, pitch_shift: 0, speaker: "default" },
    voice: { wake_word: "jarvis", mode: "wake_word", stt_model: "base" },
    language: "ru",
  };
}

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .settings()
      .then((data) => {
        const merged = { ...emptySettings(), ...(data as Partial<SettingsData>) };
        setSettings(merged as SettingsData);
      })
      .catch((e) =>
        setError(`Cannot load settings: ${e instanceof Error ? e.message : e}`),
      );
  }, []);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    try {
      await api.updateSettings({
        provider: settings.llm.provider,
        openai_key: settings.llm.openai_key,
        openai_model: settings.llm.openai_model,
        anthropic_key: settings.llm.anthropic_key,
        anthropic_model: settings.llm.anthropic_model,
        google_key: settings.llm.google_key,
        google_model: settings.llm.google_model,
        deepseek_key: settings.llm.deepseek_key,
        deepseek_model: settings.llm.deepseek_model,
        language: settings.language,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(`Save failed: ${e instanceof Error ? e.message : e}`);
    }
    setSaving(false);
  };

  if (error) {
    return (
      <div style={{ padding: "var(--j-space-6)", color: "var(--j-danger)" }}>{error}</div>
    );
  }
  if (!settings) {
    return (
      <div style={{ padding: "var(--j-space-6)", color: "var(--j-text-muted)" }}>
        Loading settings...
      </div>
    );
  }

  const saveLabel = saving ? "Сохраняю..." : saved ? "Сохранено" : "Сохранить";
  const saveColor = saved ? "var(--j-success)" : "var(--j-cyan)";

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        padding: "var(--j-space-6)",
        overflow: "auto",
      }}
    >
      <div style={{ maxWidth: "42rem", margin: "0 auto" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--j-space-3)",
            marginBottom: "var(--j-space-5)",
          }}
        >
          <SettingsIcon style={{ width: 18, height: 18, color: "var(--j-cyan)" }} />
          <h2
            style={{
              fontFamily: "var(--j-font-mono)",
              fontSize: "var(--j-text-lg)",
              letterSpacing: "var(--j-tracking-hud)",
              textTransform: "uppercase",
              color: "var(--j-text)",
            }}
          >
            Settings
          </h2>
        </div>

        <div style={{ marginBottom: "var(--j-space-5)" }}>
          <HudDivider label="ЯЗЫК" />
          <div style={{ height: "var(--j-space-3)" }} />
          <HexFrame>
            <div
              style={{
                padding: "var(--j-space-4)",
                display: "flex",
                gap: "var(--j-space-2)",
                flexWrap: "wrap",
              }}
            >
              {LANGUAGES.map((l) => {
                const selected = (settings.language || "ru") === l.id;
                return (
                  <button
                    key={l.id}
                    onClick={() => setSettings({ ...settings, language: l.id })}
                    style={{
                      padding: "var(--j-space-2) var(--j-space-4)",
                      borderRadius: "var(--j-radius-md)",
                      background: selected
                        ? "color-mix(in srgb, var(--j-cyan) 15%, transparent)"
                        : "var(--j-surface)",
                      border: `1px solid ${selected ? "var(--j-border-glow)" : "var(--j-border)"}`,
                      color: selected ? "var(--j-cyan)" : "var(--j-text-dim)",
                      fontFamily: "var(--j-font-mono)",
                      fontSize: "var(--j-text-xs)",
                      letterSpacing: "var(--j-tracking-wide)",
                      textTransform: "uppercase",
                      cursor: "pointer",
                      transition: "all var(--j-duration-base) var(--j-ease-in-out)",
                    }}
                  >
                    {l.label}
                  </button>
                );
              })}
            </div>
          </HexFrame>
        </div>

        <LlmSettings
          value={settings.llm}
          onChange={(next) => setSettings({ ...settings, llm: next })}
        />

        <AdvancedSettings />

        <button
          onClick={save}
          disabled={saving}
          style={{
            width: "100%",
            padding: "var(--j-space-3) var(--j-space-5)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "var(--j-space-2)",
            background: saved
              ? "color-mix(in srgb, var(--j-success) 12%, transparent)"
              : "color-mix(in srgb, var(--j-cyan) 12%, transparent)",
            border: `1px solid ${saved ? "var(--j-success-glow)" : "var(--j-border-glow)"}`,
            borderRadius: "var(--j-radius-md)",
            color: saveColor,
            fontFamily: "var(--j-font-mono)",
            fontSize: "var(--j-text-sm)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: saving ? "wait" : "pointer",
            opacity: saving ? 0.6 : 1,
            transition: "all var(--j-duration-base) var(--j-ease-in-out)",
          }}
        >
          <Save style={{ width: 16, height: 16 }} />
          {saveLabel}
        </button>
      </div>
    </div>
  );
}
