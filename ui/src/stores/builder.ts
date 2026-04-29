import { create } from "zustand";
import { builderApi, type BuilderPreview } from "../api/builder";

export type BuilderPhase =
  | "idle"
  | "listening"     // mic active, capturing audio
  | "transcribing"  // audio → /voice/transcribe
  | "extracting"    // text → /builder/extract
  | "asking"        // wizard mid-flow (sub-state via askingSubState)
  | "previewing"    // A6 readback
  | "deploying"
  | "done"
  | "error";

export type AskingSubState = "tts_speaking" | "listening_for_answer";
export type PreviewSubState = "tts_speaking" | "listening_for_command";

interface BuilderState {
  phase: BuilderPhase;
  askingSubState: AskingSubState;
  previewSubState: PreviewSubState;
  sessionId: string | null;
  request: string;
  questions: string[];           // full wizard question list (needed for editField)
  question: string | null;
  step: number;
  totalSteps: number;
  preview: BuilderPreview | null;
  partialSpec: BuilderPreview | null;
  transcript: string;
  error: string | null;
  _submitGen: number;  // internal — incremented on each new pipeline; invalidates stale promises

  tap: () => void;
  submitAudio: (audio: Uint8Array | ArrayBuffer, sample_rate: number) => Promise<void>;
  start: (request: string) => Promise<void>;  // text-fallback path
  answer: (text: string) => Promise<void>;
  deploy: () => Promise<void>;
  cancel: () => Promise<void>;
  /** A6 voice command: "поправь интервал" → re-enter wizard at the
   *  question whose `_question_to_key` matches `field`. No-op if the
   *  field isn't recognised in the current wizard's question list. */
  editField: (field: string) => void;
  setAskingSubState: (s: AskingSubState) => void;
  setPreviewSubState: (s: PreviewSubState) => void;
  reset: () => void;
}

const _toBase64 = (audio: Uint8Array | ArrayBuffer): string => {
  const bytes = audio instanceof Uint8Array ? audio : new Uint8Array(audio);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
};

// Same Russian-keyword rules as the backend `_question_to_key` helper —
// kept in sync via a shared parametrized vitest if a third caller appears.
// For now: small enough to duplicate; correctness covered by the editField
// vitest test below.
const _questionToKey = (question: string): string => {
  const q = question.toLowerCase();
  if (q.includes("часто") || q.includes("interval")) return "interval";
  if (q.includes("цел") || q.includes("goal")) return "goal";
  if (q.includes("услов") || q.includes("trigger")) return "trigger";
  if (q.includes("уведом") || q.includes("notify") || q.includes("куда")) return "notify_channel";
  if (q.includes("url") || q.includes("сервис")) return "target";
  if (q.includes("событ") || q.includes("категор")) return "categories";
  if (q.includes("врем") || q.includes("time")) return "time_window";
  return "";
};

export const useBuilderStore = create<BuilderState>((set, get) => ({
  phase: "idle",
  askingSubState: "tts_speaking",
  previewSubState: "tts_speaking",
  sessionId: null,
  request: "",
  questions: [],
  question: null,
  step: 0,
  totalSteps: 0,
  preview: null,
  partialSpec: null,
  transcript: "",
  error: null,
  _submitGen: 0,

  tap: () => {
    const { phase } = get();
    if (phase === "idle") set({ phase: "listening", error: null });
    else if (phase === "listening") set({ phase: "idle" });
    // Other phases: tap is a no-op (orb is disabled in UI).
  },

  editField: (field) => {
    const { questions } = get();
    const idx = questions.findIndex((q) => _questionToKey(q) === field);
    if (idx < 0) return;  // unknown field — silently no-op (UI shows preview unchanged)
    set({
      step: idx,
      question: questions[idx],
      phase: "asking",
      askingSubState: "tts_speaking",
      preview: null,  // wizard re-fills the slot
    });
  },

  submitAudio: async (audio, sample_rate) => {
    const gen = get()._submitGen + 1;
    set({ phase: "transcribing", _submitGen: gen });
    try {
      const audio_b64 = _toBase64(audio);
      const stt = await builderApi.transcribe(audio_b64, sample_rate, "ru");
      if (get()._submitGen !== gen) return;
      set({ transcript: stt.text, phase: "extracting", request: stt.text });

      const result = await builderApi.extract(stt.text, "ru");
      if (get()._submitGen !== gen) return;
      if (result.complete) {
        set({
          sessionId: result.session_id,
          preview: result.spec,
          questions: [],
          phase: "previewing",
          previewSubState: "tts_speaking",
        });
      } else {
        // Server returns `next_question` plus `step` and `total_steps`. To
        // support `editField` we also need the full question list; the
        // extractor doesn't surface it explicitly, so reconstruct it via a
        // GET to /builder/answer? — actually no, easier: extractor.py also
        // returns a `questions: string[]` field in the partial response (extend the
        // contract — see Chunk 2 update note below). For complete=true we
        // don't need it (no wizard to re-enter).
        set({
          sessionId: result.session_id,
          step: result.step,
          totalSteps: result.total_steps,
          questions: result.questions,
          question: result.next_question,
          partialSpec: result.partial_spec,
          phase: "asking",
          askingSubState: "tts_speaking",
        });
      }
    } catch (e) {
      if (get()._submitGen !== gen) return;
      set({ phase: "error", error: String(e) });
    }
  },

  start: async (request) => {
    // Text-fallback path (StarterExamples or "печатать вместо голоса").
    const gen = get()._submitGen + 1;
    set({ phase: "extracting", request, error: null, _submitGen: gen });
    try {
      const result = await builderApi.extract(request, "ru");
      if (get()._submitGen !== gen) return;
      if (result.complete) {
        set({
          sessionId: result.session_id,
          preview: result.spec,
          questions: [],
          phase: "previewing",
          previewSubState: "tts_speaking",
        });
      } else {
        set({
          sessionId: result.session_id,
          step: result.step,
          totalSteps: result.total_steps,
          questions: result.questions,
          question: result.next_question,
          partialSpec: result.partial_spec,
          phase: "asking",
          askingSubState: "tts_speaking",
        });
      }
    } catch (e) {
      if (get()._submitGen !== gen) return;
      set({ phase: "error", error: String(e) });
    }
  },

  answer: async (text) => {
    const sid = get().sessionId;
    if (!sid) return;
    try {
      const r = await builderApi.answer(sid, text);
      if (r.done && r.preview) {
        set({
          preview: r.preview,
          phase: "previewing",
          askingSubState: "tts_speaking",
          question: null,
        });
      } else {
        set({
          question: r.question ?? null,
          step: r.step ?? get().step + 1,
          askingSubState: "tts_speaking",
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
    // Increment gen BEFORE the await so in-flight promises see stale gen immediately.
    set({ _submitGen: get()._submitGen + 1 });
    if (sid) await builderApi.cancel(sid).catch(() => {});
    get().reset();
  },

  setAskingSubState: (s) => set({ askingSubState: s }),
  setPreviewSubState: (s) => set({ previewSubState: s }),

  reset: () =>
    set({
      phase: "idle",
      askingSubState: "tts_speaking",
      previewSubState: "tts_speaking",
      sessionId: null,
      request: "",
      questions: [],
      question: null,
      step: 0,
      totalSteps: 0,
      preview: null,
      partialSpec: null,
      transcript: "",
      error: null,
      _submitGen: get()._submitGen + 1,
    }),
}));
