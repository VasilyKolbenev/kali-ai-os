import { Key, Cpu } from "lucide-react";

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
  keyField,
  keyValue,
  modelField,
  modelValue,
  models,
  placeholder,
  onKeyChange,
  onModelChange,
}: {
  label: string;
  keyField: string;
  keyValue: string;
  modelField: string;
  modelValue: string;
  models: string[];
  placeholder: string;
  onKeyChange: (v: string) => void;
  onModelChange: (v: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-white/40 block mb-1">{label} API Key</label>
        <div className="flex gap-2">
          <Key className="w-4 h-4 text-white/20 mt-2" />
          <input
            type="password"
            value={keyValue}
            onChange={(e) => onKeyChange(e.target.value)}
            placeholder={placeholder}
            data-field={keyField}
            className="flex-1 bg-white/5 rounded px-3 py-2 text-sm outline-none placeholder:text-white/20 focus:bg-white/10 font-mono"
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-white/40 block mb-1">{label} Model</label>
        <div className="flex flex-wrap gap-1">
          {models.map((m) => (
            <button
              key={m}
              data-field={modelField}
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
        keyField="openai_key"
        keyValue={value.openai_key}
        modelField="openai_model"
        modelValue={value.openai_model}
        models={OPENAI_MODELS}
        placeholder="sk-..."
        onKeyChange={(v) => patch({ openai_key: v })}
        onModelChange={(v) => patch({ openai_model: v })}
      />
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="Anthropic"
          keyField="anthropic_key"
          keyValue={value.anthropic_key}
          modelField="anthropic_model"
          modelValue={value.anthropic_model}
          models={ANTHROPIC_MODELS}
          placeholder="sk-ant-..."
          onKeyChange={(v) => patch({ anthropic_key: v })}
          onModelChange={(v) => patch({ anthropic_model: v })}
        />
      </div>
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="Google"
          keyField="google_key"
          keyValue={value.google_key}
          modelField="google_model"
          modelValue={value.google_model}
          models={GOOGLE_MODELS}
          placeholder="AIza..."
          onKeyChange={(v) => patch({ google_key: v })}
          onModelChange={(v) => patch({ google_model: v })}
        />
      </div>
      <div className="mt-4 pt-4 border-t border-white/5">
        <ProviderBlock
          label="DeepSeek"
          keyField="deepseek_key"
          keyValue={value.deepseek_key}
          modelField="deepseek_model"
          modelValue={value.deepseek_model}
          models={DEEPSEEK_MODELS}
          placeholder="sk-..."
          onKeyChange={(v) => patch({ deepseek_key: v })}
          onModelChange={(v) => patch({ deepseek_model: v })}
        />
      </div>
    </div>
  );
}
