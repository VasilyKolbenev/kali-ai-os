import { useState } from "react";
import type { ReactNode } from "react";
import { api } from "../../../api/client";
import { SecretField } from "../SecretField";
import { HexFrame, HudDivider } from "../../hud";
import { ANTHROPIC_ACTIVE } from "../../../lib/modelRegistry";

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

const OPENAI_MODELS = ["gpt-5.4", "gpt-5.4-thinking", "gpt-4.1-mini", "gpt-4.1-nano"];
// OPUS-301: active Anthropic models come from the shared registry SoT.
const ANTHROPIC_MODELS = [...ANTHROPIC_ACTIVE];
const GOOGLE_MODELS = ["gemini-3.1-ultra", "gemini-3.1-pro", "gemini-3.1-flash-lite"];
const DEEPSEEK_MODELS = ["deepseek-v3.2", "deepseek-r1", "deepseek-coder-v3"];

const fieldLabelStyle = {
  display: "block",
  marginBottom: "var(--j-space-1)",
  fontSize: "var(--j-text-xs)",
  color: "var(--j-text-dim)",
  fontFamily: "var(--j-font-mono)",
  letterSpacing: "var(--j-tracking-wide)",
  textTransform: "uppercase" as const,
};

function ModelChip({
  selected,
  onClick,
  children,
  dataField,
  dataProvider,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  dataField: string;
  dataProvider: string;
}) {
  return (
    <button
      data-field={dataField}
      data-provider={dataProvider}
      onClick={onClick}
      style={{
        padding: "var(--j-space-1) var(--j-space-3)",
        borderRadius: "var(--j-radius-md)",
        background: selected
          ? "color-mix(in srgb, var(--j-cyan) 15%, transparent)"
          : "var(--j-surface)",
        border: `1px solid ${selected ? "var(--j-border-glow)" : "var(--j-border)"}`,
        color: selected ? "var(--j-cyan)" : "var(--j-text-dim)",
        fontFamily: "var(--j-font-mono)",
        fontSize: "var(--j-text-xs)",
        letterSpacing: "var(--j-tracking-wide)",
        cursor: "pointer",
        transition: "all var(--j-duration-base) var(--j-ease-in-out)",
      }}
    >
      {children}
    </button>
  );
}

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
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--j-space-3)" }}>
      <div>
        <label style={fieldLabelStyle}>{label} API Key</label>
        <SecretField
          value={keyValue}
          onChange={onKeyChange}
          placeholder={placeholder}
          onTest={onTest}
          status={status}
        />
      </div>
      <div>
        <label style={fieldLabelStyle}>{label} Model</label>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--j-space-1)" }}>
          {models.map((m) => (
            <ModelChip
              key={m}
              selected={modelValue === m}
              onClick={() => onModelChange(m)}
              dataField={modelField}
              dataProvider={providerId}
            >
              {m}
            </ModelChip>
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
    <div style={{ marginBottom: "var(--j-space-5)" }}>
      <HudDivider label="LLM ПРОВАЙДЕРЫ" />
      <div style={{ height: "var(--j-space-3)" }} />
      <HexFrame>
        <div style={{ padding: "var(--j-space-4)" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
              gap: "var(--j-space-2)",
              marginBottom: "var(--j-space-4)",
            }}
          >
            {PROVIDERS.map((p) => (
              <button
                key={p.id}
                onClick={() => patch({ provider: p.id })}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
              >
                <HexFrame active={value.provider === p.id}>
                  <div
                    style={{
                      padding: "var(--j-space-3)",
                      textAlign: "center",
                      color:
                        value.provider === p.id ? "var(--j-cyan)" : "var(--j-text-dim)",
                      fontFamily: "var(--j-font-mono)",
                      fontSize: "var(--j-text-xs)",
                      letterSpacing: "var(--j-tracking-wide)",
                      textTransform: "uppercase",
                    }}
                  >
                    {p.label}
                  </div>
                </HexFrame>
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
          <div style={{ margin: "var(--j-space-4) 0" }}>
            <HudDivider />
          </div>
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
          <div style={{ margin: "var(--j-space-4) 0" }}>
            <HudDivider />
          </div>
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
          <div style={{ margin: "var(--j-space-4) 0" }}>
            <HudDivider />
          </div>
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
      </HexFrame>
    </div>
  );
}
