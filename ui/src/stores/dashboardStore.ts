import { create } from "zustand";

interface DashboardState {
  widgets: Record<string, unknown>;
  updateWidget: (name: string, data: unknown) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  widgets: {
    sleep: null,
    tasks: null,
    calendar: null,
    spending: null,
    energy: null,
    agents: null,
  },
  updateWidget: (name, data) =>
    set((state) => ({ widgets: { ...state.widgets, [name]: data } })),
}));
