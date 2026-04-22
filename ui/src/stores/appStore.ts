import { create } from "zustand";

export type AppMode =
  | "focus"
  | "dashboard"
  | "agents"
  | "nightstand"
  | "store"
  | "activity"
  | "builder"
  | "settings";

interface AppState {
  mode: AppMode;
  kernelConnected: boolean;
  setMode: (mode: AppMode) => void;
  setKernelConnected: (connected: boolean) => void;
}

export const useAppStore = create<AppState>((set) => ({
  mode: "focus",
  kernelConnected: false,
  setMode: (mode) => set({ mode }),
  setKernelConnected: (connected) => set({ kernelConnected: connected }),
}));
