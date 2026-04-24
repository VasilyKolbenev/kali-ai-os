import { create } from "zustand";

export type OnboardingStep =
  | "welcome"
  | "api-key"
  | "mic-test"
  | "first-agent"
  | "landing";

export type ApiProvider = "openai" | "anthropic" | "google" | "deepseek";
export type MicPermission = "unknown" | "granted" | "denied";

const STEP_ORDER: OnboardingStep[] = [
  "welcome",
  "api-key",
  "mic-test",
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

  advance: () => void;
  back: () => void;
  skip: () => void;
  reset: () => void;
  setApiProvider: (provider: ApiProvider) => void;
  setApiKeyValid: (valid: boolean) => void;
  setMicPermission: (p: MicPermission) => void;
  setFirstAgentSession: (sessionId: string | null) => void;
}

export const useOnboardingStore = create<OnboardingState>((set, get) => ({
  currentStep: "welcome",
  completed: false,
  apiProvider: null,
  apiKeyValid: false,
  micPermission: "unknown",
  firstAgentSession: null,

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
    }),
  setApiProvider: (p) => set({ apiProvider: p }),
  setApiKeyValid: (v) => set({ apiKeyValid: v }),
  setMicPermission: (p) => set({ micPermission: p }),
  setFirstAgentSession: (s) => set({ firstAgentSession: s }),
}));
