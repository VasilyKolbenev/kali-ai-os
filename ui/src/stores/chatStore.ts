import { create } from "zustand";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  source?: string;
  timestamp: number;
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  addMessage: (role: "user" | "assistant", text: string, source?: string) => void;
  setLoading: (loading: boolean) => void;
  clear: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  addMessage: (role, text, source) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: crypto.randomUUID(), role, text, source, timestamp: Date.now() },
      ],
    })),
  setLoading: (isLoading) => set({ isLoading }),
  clear: () => set({ messages: [] }),
}));
