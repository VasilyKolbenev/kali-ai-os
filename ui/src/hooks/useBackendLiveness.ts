import { useEffect, useState } from "react";
import { resolveApiUrl } from "../api/endpoints";

/** Интервал проба Python-liveness. */
export const CRASH_POLL_MS = 5000;
/** Сколько «down» подряд до показа промпта (~15с — переживает медленный старт
 *  Python, где wait_for_backend_ready даёт 5с, и отсекает транзиентные блипы). */
export const CRASH_DOWN_STREAK = 3;

/**
 * true — Python-backend уверенно мёртв (а Rust :3006 жив, раз ответил).
 * Если сам :3006 недоступен (reject) — false: Rust мёртв, промпт бессмысленен
 * (его транспорт на том же сервере), это вне скоупа фичи.
 */
export function useBackendLiveness(): boolean {
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let streak = 0;

    const tick = async () => {
      try {
        const res = await fetch(resolveApiUrl("/crash/status", "GET"), { method: "GET" });
        if (!res.ok) throw new Error(String(res.status));
        const { backend_alive: alive } = (await res.json()) as { backend_alive: boolean };
        if (cancelled) return;
        if (alive) {
          streak = 0;
          setDown(false);
        } else {
          streak += 1;
          if (streak >= CRASH_DOWN_STREAK) setDown(true);
        }
      } catch {
        // :3006 не ответил — Rust мёртв; промпт не показываем
        if (!cancelled) {
          streak = 0;
          setDown(false);
        }
      }
    };

    void tick();
    const id = setInterval(tick, CRASH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return down;
}
