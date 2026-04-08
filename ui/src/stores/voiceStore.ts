import { create } from "zustand";
import type { VoiceState } from "../api/types";

interface VoiceStoreState {
  state: VoiceState;
  transcript: string;
  lastResponse: string;
  setState: (state: VoiceState) => void;
  setTranscript: (text: string) => void;
  setLastResponse: (text: string) => void;
}

export const useVoiceStore = create<VoiceStoreState>((set) => ({
  state: "idle",
  transcript: "",
  lastResponse: "",
  setState: (state) => set({ state }),
  setTranscript: (transcript) => set({ transcript }),
  setLastResponse: (lastResponse) => set({ lastResponse }),
}));
