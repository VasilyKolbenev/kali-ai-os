import { useEffect, useState } from "react";
import { Settings as SettingsIcon, Save, Key, Cpu, Globe } from "lucide-react";
import { apiUrl } from "../../api/runtime";

interface SettingsData {
  llm: {
    provider: string;
    openai_key: string;
    openai_model: string;
    anthropic_key: string;
    anthropic_model: string;
    google_key: string;
    google_model: string;
    deepseek_key: string;
    deepseek_model: string;
  };
  tts: { enabled: boolean; pitch_shift: number; speaker: string };
  voice: { wake_word: string; mode: string; stt_model: string };
  language: string; // "ru" | "en" | "zh"
}

// Актуальные модели — апрель 2026
const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "google", label: "Google" },
  { id: "deepseek", label: "DeepSeek" },
] as const;

const OPENAI_MODELS = [
  "gpt-5.4",           // Flagship (March 2026)
  "gpt-5.4-thinking",  // Extended reasoning
  "gpt-4.1-mini",      // Fast & cheap
  "gpt-4.1-nano",      // Fastest
];
const ANTHROPIC_MODELS = [
  "claude-sonnet-4-20250514",   // Best value (near-Opus)
  "claude-opus-4-20250414",     // Most capable
  "claude-haiku-4-20250414",    // Fastest
];
const GOOGLE_MODELS = [
  "gemini-3.1-ultra",      // Top reasoning
  "gemini-3.1-pro",        // Balanced
  "gemini-3.1-flash-lite", // Speed optimized
];
const DEEPSEEK_MODELS = [
  "deepseek-v3.2",       // 90% of GPT-5.4 at 1/50 cost
  "deepseek-r1",          // Reasoning model
  "deepseek-coder-v3",   // Code specialist
];

const LANGUAGES = [
  { id: "ru", label: "Русский" },
  { id: "en", label: "English" },
  { id: "zh", label: "中文" },
];

export function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [googleKey, setGoogleKey] = useState("");
  const [deepseekKey, setDeepseekKey] = useState("");

  useEffect(() => {
    fetch(apiUrl("/settings"))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: SettingsData) => {
        setSettings(data);
        setOpenaiKey(data.llm?.openai_key || "");
        setAnthropicKey(data.llm?.anthropic_key || "");
        setGoogleKey(data.llm?.google_key || "");
        setDeepseekKey(data.llm?.deepseek_key || "");
      })
      .catch((e) => setError(`Cannot load settings: ${e.message}`));
  }, []);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    setSaved(false);
    try {
      await fetch(apiUrl("/settings"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: settings.llm.provider,
          openai_key: openaiKey,
          openai_model: settings.llm.openai_model,
          anthropic_key: anthropicKey,
          anthropic_model: settings.llm.anthropic_model,
          google_key: googleKey,
          google_model: settings.llm.google_model,
          deepseek_key: deepseekKey,
          deepseek_model: settings.llm.deepseek_model,
          language: settings.language,
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch {}
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

        {/* Language */}
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

        {/* LLM Provider */}
        <div className="glass p-4 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <Cpu className="w-4 h-4 text-[var(--j-cyan)]" />
            <span className="text-sm font-medium">LLM Provider</span>
          </div>
          <div className="flex gap-2 mb-4">
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                onClick={() =>
                  setSettings({ ...settings, llm: { ...settings.llm, provider: p.id } })
                }
                className={`px-4 py-2 rounded text-xs transition ${
                  settings.llm.provider === p.id
                    ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30"
                    : "bg-white/5 text-white/40 border border-white/10"
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* OpenAI settings */}
          <div className="space-y-3">
            <div>
              <label className="text-xs text-white/40 block mb-1">OpenAI API Key</label>
              <div className="flex gap-2">
                <Key className="w-4 h-4 text-white/20 mt-2" />
                <input
                  type="password"
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  placeholder="sk-..."
                  className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 font-mono"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-white/40 block mb-1">OpenAI Model</label>
              <div className="flex flex-wrap gap-1">
                {OPENAI_MODELS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setSettings({ ...settings, llm: { ...settings.llm, openai_model: m } })}
                    className={`px-3 py-1.5 rounded text-xs transition ${settings.llm.openai_model === m ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30" : "bg-white/5 text-white/40 border border-white/10"}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Anthropic settings */}
          <div className="space-y-3 mt-4 pt-4 border-t border-white/5">
            <div>
              <label className="text-xs text-white/40 block mb-1">Anthropic API Key</label>
              <div className="flex gap-2">
                <Key className="w-4 h-4 text-white/20 mt-2" />
                <input
                  type="password"
                  value={anthropicKey}
                  onChange={(e) => setAnthropicKey(e.target.value)}
                  placeholder="sk-ant-..."
                  className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 font-mono"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-white/40 block mb-1">Anthropic Model</label>
              <div className="flex flex-wrap gap-1">
                {ANTHROPIC_MODELS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setSettings({ ...settings, llm: { ...settings.llm, anthropic_model: m } })}
                    className={`px-3 py-1.5 rounded text-xs transition ${settings.llm.anthropic_model === m ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30" : "bg-white/5 text-white/40 border border-white/10"}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Google settings */}
          <div className="space-y-3 mt-4 pt-4 border-t border-white/5">
            <div>
              <label className="text-xs text-white/40 block mb-1">Google API Key</label>
              <div className="flex gap-2">
                <Key className="w-4 h-4 text-white/20 mt-2" />
                <input
                  type="password"
                  value={googleKey}
                  onChange={(e) => setGoogleKey(e.target.value)}
                  placeholder="AIza..."
                  className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 font-mono"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-white/40 block mb-1">Google Model</label>
              <div className="flex flex-wrap gap-1">
                {GOOGLE_MODELS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setSettings({ ...settings, llm: { ...settings.llm, google_model: m } })}
                    className={`px-3 py-1.5 rounded text-xs transition ${settings.llm.google_model === m ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30" : "bg-white/5 text-white/40 border border-white/10"}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* DeepSeek settings */}
          <div className="space-y-3 mt-4 pt-4 border-t border-white/5">
            <div>
              <label className="text-xs text-white/40 block mb-1">DeepSeek API Key</label>
              <div className="flex gap-2">
                <Key className="w-4 h-4 text-white/20 mt-2" />
                <input
                  type="password"
                  value={deepseekKey}
                  onChange={(e) => setDeepseekKey(e.target.value)}
                  placeholder="sk-..."
                  className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 font-mono"
                />
              </div>
            </div>
            <div>
              <label className="text-xs text-white/40 block mb-1">DeepSeek Model</label>
              <div className="flex flex-wrap gap-1">
                {DEEPSEEK_MODELS.map((m) => (
                  <button
                    key={m}
                    onClick={() => setSettings({ ...settings, llm: { ...settings.llm, deepseek_model: m } })}
                    className={`px-3 py-1.5 rounded text-xs transition ${settings.llm.deepseek_model === m ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30" : "bg-white/5 text-white/40 border border-white/10"}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Save button */}
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
