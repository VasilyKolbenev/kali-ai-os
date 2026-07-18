import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

export const STARTUP_EVENT = "startup://state";
export const RECONCILE_MS = 2000;

/**
 * Авторитетный Rust startup-label (`state_label`), либо null до первого чтения.
 *
 * Контракт порядка:
 * 1. `listen()` вызывается первым; ни один `invoke` не происходит, пока он не
 *    завершится — поэтому переход не может проскочить между чтением и подпиской.
 * 2. resolve → один начальный `reconcile()`, затем интервал.
 * 3. reject → контролируемый polling-fallback (без unhandled rejection).
 * 4. События авторитетны: результат `invoke` отбрасывается, если во время его
 *    полёта пришло событие.
 */
export function useStartupState(): string | null {
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    let polling = false;
    let eventSeq = 0; // инкремент на каждом живом событии
    let intervalId: ReturnType<typeof setInterval> | undefined;

    const reconcile = async () => {
      if (polling || cancelled) return; // без перекрывающихся invoke
      polling = true;
      const seqAtDispatch = eventSeq; // эпоха событий на момент чтения
      try {
        const cur = await invoke<string>("get_startup_state");
        // События авторитетны: если во время полёта пришло событие, его
        // значение свежее — отбрасываем (возможно устаревший) результат.
        if (!cancelled && eventSeq === seqAtDispatch) setLabel(cur);
      } catch {
        /* Rust IPC ещё не готов — держим прежнее; следующий poll повторит. */
      } finally {
        polling = false;
      }
    };

    /** Начальное чтение + периодический self-heal. Только после settle listen. */
    const startPolling = () => {
      if (cancelled || intervalId !== undefined) return;
      void reconcile();
      intervalId = setInterval(() => {
        void reconcile();
      }, RECONCILE_MS);
    };

    listen<string>(STARTUP_EVENT, (e) => {
      if (cancelled) return;
      eventSeq += 1;
      setLabel(e.payload);
    }).then(
      (un) => {
        if (cancelled) {
          un(); // размонтировались во время await → снимаем подписку сразу
          return;
        }
        unlisten = un;
        startPolling();
      },
      () => {
        // listen недоступен → контролируемый polling-fallback; отказ обработан
        // здесь, поэтому он никогда не всплывает как unhandled rejection.
        startPolling();
      },
    );

    return () => {
      cancelled = true;
      if (intervalId !== undefined) clearInterval(intervalId);
      if (unlisten) unlisten();
    };
  }, []);

  return label;
}
