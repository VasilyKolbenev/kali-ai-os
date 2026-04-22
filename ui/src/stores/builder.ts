import { create } from "zustand";
import { builderApi, BuilderPreview } from "../api/builder";

export type BuilderPhase =
  | "idle"
  | "asking"
  | "generating"
  | "previewing"
  | "deploying"
  | "done"
  | "error";

interface BuilderState {
  phase: BuilderPhase;
  sessionId: string | null;
  request: string;
  question: string | null;
  step: number;
  totalSteps: number;
  preview: BuilderPreview | null;
  error: string | null;

  start: (request: string) => Promise<void>;
  answer: (text: string) => Promise<void>;
  deploy: () => Promise<void>;
  cancel: () => Promise<void>;
  reset: () => void;
}

export const useBuilderStore = create<BuilderState>((set, get) => ({
  phase: "idle",
  sessionId: null,
  request: "",
  question: null,
  step: 0,
  totalSteps: 0,
  preview: null,
  error: null,

  start: async (request) => {
    set({ phase: "asking", request, error: null });
    try {
      const r = await builderApi.start(request);
      set({
        sessionId: r.session_id,
        question: r.question,
        totalSteps: r.total_steps,
        step: 0,
      });
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  answer: async (text) => {
    const sid = get().sessionId;
    if (!sid) return;
    try {
      const r = await builderApi.answer(sid, text);
      if (r.done && r.preview) {
        set({ phase: "previewing", preview: r.preview, question: null });
      } else {
        set({
          question: r.question ?? null,
          step: r.step ?? get().step + 1,
        });
      }
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  deploy: async () => {
    const sid = get().sessionId;
    if (!sid) return;
    set({ phase: "deploying" });
    try {
      await builderApi.deploy(sid);
      set({ phase: "done" });
    } catch (e) {
      set({ phase: "error", error: String(e) });
    }
  },

  cancel: async () => {
    const sid = get().sessionId;
    if (sid) await builderApi.cancel(sid).catch(() => {});
    get().reset();
  },

  reset: () =>
    set({
      phase: "idle",
      sessionId: null,
      request: "",
      question: null,
      step: 0,
      totalSteps: 0,
      preview: null,
      error: null,
    }),
}));
