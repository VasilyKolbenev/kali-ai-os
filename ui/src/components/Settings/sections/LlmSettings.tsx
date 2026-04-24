import { useState } from "react";
import { Cpu } from "lucide-react";
import { api } from "../../../api/client";
import { SecretField } from "../SecretField";

type CheckStatus = "unknown" | "checking" | "valid" | "invalid";

export interface LlmSettingsValue {
  provider: string;
  openai_key: string;
  openai_model: string;
  anthropic_key: string;
  anthropic_model: string;
  google_key: string;
  google_model: string;
  deepseek_key: string;
  deepseek_model: string;
}

interface LlmSettingsProps {
  value: LlmSettingsValue;
  onChange: (next: LlmSettingsValue) => void;
}

const PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "anthropic", label: "Anthropic" },
  { id: "google", label: "Google" },
  { id: "deepseek", label: "DeepSeek" },
] as const;

const OPENAI_MODELS = [
  "gpt-5.4",
  "gpt-5.4-thinking",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
];
const ANTHROPIC_MODELS = [
  "claude-sonnet-4-20250514",
  "claude-opus-4-20250414",
  "claude-haiku-4-20250414",
];
const GOOGLE_MODELS = [
  "gemini-3.1-ultra",
  "gemini-3.1-pro",
  "gemini-3.1-flash-lite",
];
const DEEPSEEK_MODELS = [
  "deepseek-v3.2",
  "deepseek-r1",
  "deepseek-coder-v3",
];

function ProviderBlock({
  label,
  providerId,
  keyValue,
  modelField,
  modelValue,
  models,
  placeholder,
  status,
  onKeyChange,
  onModelChange,
  onTest,
}: {
  label: string;
  providerId: string;
  keyValue: string;
  modelField: string;
  modelValue: string;
  models: string[];
  placeholder: string;
  status: CheckStatus;
  onKeyChange: (v: string) => void;
  onModelChange: (v: string) => void;
  onTest: () => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-white/40 block mb-1">{label} API Key</label>
        <SecretField
          value={keyValue}
          onChange={onKeyChange}
          placeholder={placeholder}
          onTest={onTest}
          status={status}
        />
      </div>
      <div>
        <label className="text-xs text-white/40 block mb-1">{label} Model</label>
        <div className="flex flex-wrap gap-1">
          {models.map((m) => (
            <button
              key={m}
              data-field={modelField}
              data-provider={providerId}
              onClick={() => onModelChange(m)}
              className={`px-3 py-1.5 rounded text-xs transition ${
                modelValue === m
                  ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30"
                  : "bg-white/5 text-white/40 border border-white/10"
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function LlmSettings({ value, onChange }: LlmSettingsProps) {
  const patch = (partial: Partial<LlmSettingsValue>) => onChange({ ...value, ...partial });

  const [statuses, setStatuses] = useState<Record<string, CheckStatus>>({
    openai: "unknown",
    anthropic: "unknown",
    google: "unknown",
    deepseek: "unknown",
  });

  async function testKey(provider: string, key: string) {
    if (!key) return;
    setStatuses((s) => ({ ...s, [provider]: "checking" }));
    try {
      const res = await api.testApiKey(provider, key);
      setStatuses((s) => ({ ...s, [provider]: res.ok ? "valid" : "invalid" }));
    } catch {
      setStatuses((s) => ({ ...s, [provider]: "invalid" }));
    }
  }

  return (
    <div className="glass p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Cpu className="w-4 h-4 text-[var(--j-cyan)]" />
        <span className="text-sm font-medium">LLM Provider</span>
      </div>
      <div className="flex gap-2 mb-4">
        {PROVIDERS.map((p) => (
          <button
            key={p.id}
            onClick={() => patch({ provider: p.id })}
            className={`px-4 py-2 rounded text-xs transition ${
              value.provider === p.id
                ? "bg-[var(--j-cyan)]/20 text-[var(--j-cyan)] border border-[var(--j-cyan)]/30"
                : "bg-white/5 text-white/40 border border-white/10"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      <ProviderBlock
        label="OpenAI"
        providerId="openai"
        keyValue={value.openai_key}
        modelField="openai_model"
        modelValue={value.openai_model}
        models={OPENAI_MODELS}
        placeholder="sk-..."
        status={statuses.openai}
        onKeyChange={(v) => {
          patch({ openai_key: v });
          setStatuses((s) => ({ ...s, openai: "unknown" }));
        }}
        onModelChange={(v) => patch({ openai_model: v })}
        onTest={() => testKey("openai", value.openai_key)}
      />
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="Anthropic"
          providerId="anthropic"
          keyValue={value.anthropic_key}
          modelField="anthropic_model"
          modelValue={value.anthropic_model}
          models={ANTHROPIC_MODELS}
          placeholder="sk-ant-..."
          status={statuses.anthropic}
          onKeyChange={(v) => {
            patch({ anthropic_key: v });
            setStatuses((s) => ({ ...s, anthropic: "unknown" }));
          }}
          onModelChange={(v) => patch({ anthropic_model: v })}
          onTest={() => testKey("anthropic", value.anthropic_key)}
        />
      </div>
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="Google"
          providerId="google"
          keyValue={value.google_key}
          modelField="google_model"
          modelValue={value.google_model}
          models={GOOGLE_MODELS}
          placeholder="AIza..."
          status={statuses.google}
          onKeyChange={(v) => {
            patch({ google_key: v });
            setStatuses((s) => ({ ...s, google: "unknown" }));
          }}
          onModelChange={(v) => patch({ google_model: v })}
          onTest={() => testKey("google", value.google_key)}
        />
      </div>
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="DeepSeek"
          providerId="deepseek"
          keyValue={value.deepseek_key}
          modelField="deepseek_model"
          modelValue={value.deepseek_model}
          models={DEEPSEEK_MODELS}
          placeholder="sk-..."
          status={statuses.deepseek}
          onKeyChange={(v) => {
            patch({ deepseek_key: v });
            setStatuses((s) => ({ ...s, deepseek: "unknown" }));
          }}
          onModelChange={(v) => patch({ deepseek_model: v })}
          onTest={() => testKey("deepseek", value.deepseek_key)}
        />
      </div>
    </div>
  );
}
