// ui/src/api/builder.ts
import { resolveApiUrl } from "./endpoints";

export interface BuilderStartResponse {
  session_id: string;
  question: string;
  total_steps: number;
  template: string | null;
}

export interface BuilderAnswerResponse {
  done: boolean;
  question?: string;
  step?: number;
  total_steps?: number;
  preview?: BuilderPreview;
}

export interface BuilderPreview {
  name: string;
  description: string;
  type: string;
  template: string | null;
  config: Record<string, unknown>;
}

export type ExtractResponse =
  | { complete: true; session_id: string; spec: BuilderPreview }
  | {
      complete: false;
      session_id: string;
      step: number;
      total_steps: number;
      /** Full wizard question list — needed for editField (jump-to-field). */
      questions: string[];
      next_question: string;
      partial_spec: BuilderPreview;
    };

export interface TranscribeResponse {
  text: string;
  language: string;
  duration_ms: number;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(resolveApiUrl(path, "POST"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(err.error || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const builderApi = {
  // existing
  start: (request: string) =>
    postJson<BuilderStartResponse>("/builder/start", { request }),
  answer: (session_id: string, answer: string) =>
    postJson<BuilderAnswerResponse>("/builder/answer", { session_id, answer }),
  deploy: (session_id: string) =>
    postJson<{ status: string; name?: string }>("/builder/deploy", { session_id }),
  cancel: (session_id: string) =>
    postJson<{ status: string }>("/builder/cancel", { session_id }),

  // new — A4 fast-path
  extract: (request: string, language: string = "ru") =>
    postJson<ExtractResponse>("/builder/extract", { request, language }),

  // new — STT
  transcribe: (audio_b64: string, sample_rate: number, language: string = "ru") =>
    postJson<TranscribeResponse>("/voice/transcribe", { audio_b64, sample_rate, language }),

  // new — TTS playback (returns once audio finishes; duration is server-side)
  say: (text: string, language: string = "ru") =>
    postJson<{ status: string; duration: number }>("/tts/speak", { text, language }),
};
