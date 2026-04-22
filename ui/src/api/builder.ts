import { apiUrl } from "./runtime";

export interface BuilderStartResponse {
  session_id: string;
  question: string;
  total_steps: number;
  template: string | null;
}

export interface BuilderPreview {
  name: string;
  description: string;
  type: string;
  template: string | null;
  config: Record<string, unknown>;
}

export interface BuilderAnswerResponse {
  done: boolean;
  question?: string;
  step?: number;
  total_steps?: number;
  preview?: BuilderPreview;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error((err as { error?: string }).error || `HTTP ${r.status}`);
  }
  return r.json() as Promise<T>;
}

export const builderApi = {
  start: (request: string) =>
    postJson<BuilderStartResponse>("/builder/start", { request }),
  answer: (session_id: string, answer: string) =>
    postJson<BuilderAnswerResponse>("/builder/answer", { session_id, answer }),
  deploy: (session_id: string) =>
    postJson<{ status: string; name?: string }>("/builder/deploy", { session_id }),
  cancel: (session_id: string) =>
    postJson<{ status: string }>("/builder/cancel", { session_id }),
};
