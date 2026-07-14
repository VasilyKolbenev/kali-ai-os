import { create } from "zustand";
import { resolveApiUrl } from "../api/endpoints";

export type UpdaterPhase =
  | "idle" | "available" | "downloading" | "ready" | "installing" | "error";

export interface UpdaterManifest {
  version: string;
  pub_date: string;
  notes: string;
  assets: { name: string; url: string; sha256: string; size: number }[];
}

interface UpdaterSnapshot {
  phase: UpdaterPhase;
  current: string;
  available: UpdaterManifest | null;
  total: number;
  downloaded: number;
  error: string | null;
}

interface UpdaterState extends UpdaterSnapshot {
  dismissed: boolean;
  check: () => Promise<void>;
  download: () => Promise<void>;
  install: () => Promise<void>;
  dismiss: () => void;
}

const POLL_MS = 700;
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function callUpdater(path: string, method: "GET" | "POST"): Promise<UpdaterSnapshot> {
  const res = await fetch(resolveApiUrl(path, method), { method });
  if (!res.ok) throw new Error(`updater ${path}: ${res.status}`);
  return res.json();
}

function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/** Тест-хук: сбросить поллинг между тестами (см. beforeEach в тестах стора). */
export function stopPollForTests() {
  stopPoll();
}

export const useUpdaterStore = create<UpdaterState>((set, get) => ({
  phase: "idle",
  current: "",
  available: null,
  total: 0,
  downloaded: 0,
  error: null,
  dismissed: false,

  // Оффлайн/недоступный backend = тихий пропуск (спека)
  check: async () => {
    try {
      const snap = await callUpdater("/updater/check", "POST");
      const prev = get().available?.version;
      set({ ...snap, dismissed: snap.available?.version === prev ? get().dismissed : false });
    } catch { /* silent */ }
  },

  download: async () => {
    try {
      const snap = await callUpdater("/updater/download", "POST");
      set(snap);
      stopPoll();
      pollTimer = setInterval(async () => {
        try {
          const s = await callUpdater("/updater/status", "GET");
          set(s);
          if (s.phase !== "downloading") stopPoll();
        } catch { /* держим последний снапшот */ }
      }, POLL_MS);
    } catch { /* silent */ }
  },

  install: async () => {
    try {
      set({ phase: "installing" });
      await callUpdater("/updater/install", "POST");
      // дальше апп закроет Rust — UI ничего не делает
    } catch {
      set({ phase: "error", error: "Не удалось запустить установку — скачай релиз вручную" });
    }
  },

  dismiss: () => set({ dismissed: true }),
}));
