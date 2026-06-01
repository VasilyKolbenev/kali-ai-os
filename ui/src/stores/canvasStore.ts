import { create } from "zustand";

export interface CanvasWidget {
  id: string;
  type: "stat_card" | "bar_chart" | "line_chart" | "progress" | "table" | "markdown";
  title: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface CanvasState {
  widgets: CanvasWidget[];
  addOrUpdate: (widget: CanvasWidget) => void;
  remove: (id: string) => void;
  clear: () => void;
  setWidgets: (widgets: CanvasWidget[]) => void;
}

export const useCanvasStore = create<CanvasState>((set) => ({
  widgets: [],

  addOrUpdate: (widget) =>
    set((state) => {
      const idx = state.widgets.findIndex((w) => w.id === widget.id);
      if (idx >= 0) {
        const updated = [...state.widgets];
        updated[idx] = widget;
        return { widgets: updated };
      }
      return { widgets: [...state.widgets, widget] };
    }),

  remove: (id) =>
    set((state) => ({
      widgets: state.widgets.filter((w) => w.id !== id),
    })),

  clear: () => set({ widgets: [] }),

  setWidgets: (widgets) => set({ widgets }),
}));
