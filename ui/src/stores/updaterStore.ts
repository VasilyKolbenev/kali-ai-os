import { create } from "zustand";
import { resolveApiUrl } from "../api/endpoints";

export type UpdaterPhase =
  | "disabled" | "idle" | "available" | "downloading" | "ready" | "installing" | "error";

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
// Число подряд-провалов status-поллинга, после которого признаём потерю связи.
// Блип на 1-2 запроса на фоне 4.2 ГБ скачивания переживаем (держим снапшот).
const MAX_POLL_FAILS = 5;
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
      // Транзиентный обрыв во время 4.2 ГБ скачивания не должен ронять поллинг —
      // держим последний снапшот и само-восстанавливаемся; но после
      // MAX_POLL_FAILS подряд признаём потерю связи (можно продолжить via Range).
      let fails = 0;
      pollTimer = setInterval(async () => {
        try {
          const s = await callUpdater("/updater/status", "GET");
          fails = 0;
          set(s);
          if (s.phase !== "downloading") stopPoll();
        } catch {
          fails += 1;
          if (fails >= MAX_POLL_FAILS) {
            stopPoll();
            set({ phase: "error", error: "Потеряна связь во время загрузки — можно продолжить" });
          }
          // иначе держим последний снапшот (само-восстановление на блипе)
        }
      }, POLL_MS);
    } catch {
      // Прямое действие пользователя (клик «Скачать») — молчать нельзя, в
      // отличие от фоновой check(). Даём обратную связь и не оставляем поллинг.
      stopPoll();
      set({ phase: "error", error: "Не удалось начать загрузку — проверь, что KALI запущена" });
    }
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
