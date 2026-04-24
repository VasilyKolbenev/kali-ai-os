import { useEffect, useState } from "react";
import { Settings as SettingsIcon, Save, Globe } from "lucide-react";
import { api } from "../../api/client";
import { LlmSettings, type LlmSettingsValue } from "./sections/LlmSettings";

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

  if (error) return <div className="p-8 text-[var(--j-red)]">{error}</div>;
  if (!settings) return <div className="p-8 text-white/30">Loading settings...</div>;

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <SettingsIcon className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium">Settings</h2>
        </div>

        <div className="glass p-4 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <Globe className="w-4 h-4 text-[var(--j-cyan)]" />
            <span className="text-sm font-medium">Language / Язык</span>
          </div>
          <div className="flex gap-2">
            {LANGUAGES.map((l) => (
              <button
                key={l.id}
                onClick={() => setSettings({ ...settings, language: l.id })}
                className={`px-4 py-2 rounded text-xs transition ${
                  (settings.language || "ru") === l.id
                    ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30"
                    : "bg-white/5 text-white/40 border border-white/10"
                }`}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <LlmSettings
          value={settings.llm}
          onChange={(next) => setSettings({ ...settings, llm: next })}
        />

        <button
          onClick={save}
          disabled={saving}
          className="w-full glass p-3 flex items-center justify-center gap-2 text-sm transition hover:bg-white/5"
          style={{ color: saved ? "var(--j-green)" : "var(--j-cyan)" }}
        >
          <Save className="w-4 h-4" />
          {saving ? "Saving..." : saved ? "Saved!" : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
