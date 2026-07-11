import { create } from "zustand";
import { persist } from "zustand/middleware";

export type OnboardingStep =
  | "welcome"
  | "api-key"
  | "models-download"
  | "mic-test"
  | "profile"
  | "first-agent"
  | "landing";

export type ApiProvider = "openai" | "anthropic" | "google" | "deepseek";
export type MicPermission = "unknown" | "granted" | "denied";

export interface ModelProgress {
  filename: string;
  description: string;
  downloaded_bytes: number;
  total_bytes: number;
}

const STEP_ORDER: OnboardingStep[] = [
  "welcome",
  "api-key",
  "models-download",
  "mic-test",
  "profile",
  "first-agent",
  "landing",
];

interface OnboardingState {
  currentStep: OnboardingStep;
  completed: boolean;
  apiProvider: ApiProvider | null;
  apiKeyValid: boolean;
  micPermission: MicPermission;
  firstAgentSession: string | null;
  modelProgress: Record<string, ModelProgress>;

  advance: () => void;
  back: () => void;
  skip: () => void;
  reset: () => void;
  setApiProvider: (provider: ApiProvider) => void;
  setApiKeyValid: (valid: boolean) => void;
  setMicPermission: (p: MicPermission) => void;
  setFirstAgentSession: (sessionId: string | null) => void;
  setModelProgress: (p: ModelProgress) => void;
}

// `completed` is persisted locally so a returning user NEVER falls back into
// the wizard while the kernel is still booting (cold start loads voice models
// for 40-60 s); the kernel-offline banner covers the dead-backend case.
export const useOnboardingStore = create<OnboardingState>()(
  persist(
    (set, get) => ({
  currentStep: "welcome",
  completed: false,
  apiProvider: null,
  apiKeyValid: false,
  micPermission: "unknown",
  firstAgentSession: null,
  modelProgress: {},

  advance: () => {
    const { currentStep } = get();
    const idx = STEP_ORDER.indexOf(currentStep);
    if (idx === STEP_ORDER.length - 1) {
      set({ completed: true });
    } else {
      set({ currentStep: STEP_ORDER[idx + 1] });
    }
  },
  back: () => {
    const { currentStep } = get();
    const idx = STEP_ORDER.indexOf(currentStep);
    if (idx > 0) set({ currentStep: STEP_ORDER[idx - 1] });
  },
  skip: () => set({ completed: true }),
  reset: () =>
    set({
      currentStep: "welcome",
      completed: false,
      apiProvider: null,
      apiKeyValid: false,
      micPermission: "unknown",
      firstAgentSession: null,
      modelProgress: {},
    }),
  setApiProvider: (p) => set({ apiProvider: p }),
  setApiKeyValid: (v) => set({ apiKeyValid: v }),
  setMicPermission: (p) => set({ micPermission: p }),
  setFirstAgentSession: (s) => set({ firstAgentSession: s }),
  setModelProgress: (p) =>
    set((state) => ({
      modelProgress: { ...state.modelProgress, [p.filename]: p },
    })),
    }),
    {
      name: "kali-onboarding",
      partialize: (s) => ({ completed: s.completed }),
    },
  ),
);
