import { create } from "zustand";
import type { VoiceState } from "../api/types";

interface VoiceStoreState {
  state: VoiceState;
  pipelineActive: boolean;
  transcript: string;
  lastResponse: string;
  setState: (state: VoiceState) => void;
  setPipelineActive: (active: boolean) => void;
  setTranscript: (text: string) => void;
  setLastResponse: (text: string) => void;
}

export const useVoiceStore = create<VoiceStoreState>((set) => ({
  state: "idle",
  pipelineActive: false,
  transcript: "",
  lastResponse: "",
  setState: (state) => set({ state }),
  setPipelineActive: (pipelineActive) => set({ pipelineActive }),
  setTranscript: (transcript) => set({ transcript }),
  setLastResponse: (lastResponse) => set({ lastResponse }),
}));
