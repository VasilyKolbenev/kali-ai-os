import type { ApiProvider } from "../../stores/onboardingStore";

export interface ProviderMeta {
  id: ApiProvider;
  label: string;
  helpUrl: string;
  placeholder: string;
}

export const PROVIDERS: ProviderMeta[] = [
  {
    id: "openai",
    label: "OpenAI",
    helpUrl: "https://platform.openai.com/api-keys",
    placeholder: "sk-...",
  },
  {
    id: "anthropic",
    label: "Anthropic",
    helpUrl: "https://console.anthropic.com/settings/keys",
    placeholder: "sk-ant-...",
  },
  {
    id: "google",
    label: "Google",
    helpUrl: "https://aistudio.google.com/app/apikey",
    placeholder: "AIza...",
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    helpUrl: "https://platform.deepseek.com/api_keys",
    placeholder: "sk-...",
  },
];
