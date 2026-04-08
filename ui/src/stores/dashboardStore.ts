import { create } from "zustand";

interface DashboardState {
  widgets: Record<string, unknown>;
  updateWidget: (name: string, data: unknown) => void;
}

export const useDashboardStore = create<DashboardState>((set) => ({
  widgets: {
    sleep: { hours: 7.2, hrv: 51 },
    tasks: { done: 5, total: 8 },
    calendar: { next: "Team call", time: "10:00 AM" },
    spending: { amount: 340, currency: "$" },
    energy: { calories: 1800 },
    agents: { running: 0 },
  },
  updateWidget: (name, data) =>
    set((state) => ({ widgets: { ...state.widgets, [name]: data } })),
}));
