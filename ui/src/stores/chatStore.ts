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
  pendingMessage: string | null;
  addMessage: (role: "user" | "assistant", text: string, source?: string) => void;
  setLoading: (loading: boolean) => void;
  setPendingMessage: (text: string | null) => void;
  clear: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  isLoading: false,
  pendingMessage: null,
  addMessage: (role, text, source) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { id: crypto.randomUUID(), role, text, source, timestamp: Date.now() },
      ],
    })),
  setLoading: (isLoading) => set({ isLoading }),
  setPendingMessage: (text) => set({ pendingMessage: text }),
  clear: () => set({ messages: [] }),
}));
