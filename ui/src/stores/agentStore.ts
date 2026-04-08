import { create } from "zustand";

interface AgentInfo {
  name: string;
  status: string;
  description?: string;
}

interface AgentStoreState {
  agents: AgentInfo[];
  setAgents: (agents: AgentInfo[]) => void;
  updateAgent: (name: string, status: string) => void;
}

export const useAgentStore = create<AgentStoreState>((set) => ({
  agents: [],
  setAgents: (agents) => set({ agents }),
  updateAgent: (name, status) =>
    set((state) => ({
      agents: state.agents.some((a) => a.name === name)
        ? state.agents.map((a) => (a.name === name ? { ...a, status } : a))
        : [...state.agents, { name, status }],
    })),
}));
