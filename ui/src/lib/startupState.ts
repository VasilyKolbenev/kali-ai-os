export type StartupKind = "booting" | "ready" | "degraded" | "failed";

export interface StartupView {
  kind: StartupKind;
  /** Стабильный slug: "not_found" | "crashed" | … | "generic" | "protocol_error". */
  reason: string;
  title: string;
  body: string;
}

const BOOTING = new Set(["shell_ready", "rust_ready", "python_starting"]);

/** Терминальные (красные): нужны действия пользователя — supervisor не восстановит. */
const RED = new Set([
  "failed",
  "failed:rust_startup",
  "failed:gave_up",
  "degraded:not_found",
  "degraded:port_occupied",
]);

/** Восстановимые (янтарные): supervisor активно перезапускает. */
const AMBER = new Set([
  "degraded:crashed",
  "degraded:foreign_backend",
  "degraded:spawn_failed",
  "degraded:process_unknown",
]);

// RU-копия — утверждена владельцем 2026-07-18.
const COPY: Record<string, { title: string; body: string }> = {
  not_found: {
    title: "Компонент KALI не найден",
    body: "Один из файлов приложения отсутствует. Переустанови KALI и запусти приложение снова.",
  },
  crashed: {
    title: "Ядро перезапускается",
    body: "Локальный сервис неожиданно остановился. KALI автоматически запускает его снова.",
  },
  port_occupied: {
    title: "Локальный сервис занят",
    body: "Закрой другую копию KALI и перезапусти приложение. Если ошибка повторится, перезагрузи компьютер.",
  },
  foreign_backend: {
    title: "Обнаружена другая копия ядра",
    body: "Закрой другие процессы KALI. После этого восстановление продолжится автоматически.",
  },
  spawn_failed: {
    title: "Повторяю запуск ядра",
    body: "Первая попытка не удалась. KALI повторит запуск автоматически.",
  },
  process_unknown: {
    title: "Проверяю состояние ядра",
    body: "KALI временно не может подтвердить состояние локального процесса и повторяет проверку.",
  },
  degraded_generic: {
    title: "Восстанавливаю ядро",
    body: "KALI обнаружила временную проблему и пытается восстановить работу автоматически.",
  },
  rust_startup: {
    title: "Не удалось запустить локальный сервис",
    body: "Перезапусти KALI. Если ошибка повторится, передай разработчику логи из папки %APPDATA%\\KALI\\logs.",
  },
  gave_up: {
    title: "Ядро не удалось восстановить",
    body: "Автоматические попытки завершены. Перезапусти KALI; если ошибка повторится, передай диагностические логи.",
  },
  failed_generic: {
    title: "Не удалось завершить запуск KALI",
    body: "Перезапусти приложение. Если ошибка повторится, передай диагностические логи.",
  },
  protocol_error: {
    title: "Не удалось определить состояние запуска",
    body: "Перезапусти KALI. Если ошибка повторится, передай диагностические логи.",
  },
};

/** Поиск копии с защитным fallback по kind (никогда не возвращает undefined). */
function copyFor(reason: string, kind: "failed" | "degraded") {
  return COPY[reason] ?? (kind === "failed" ? COPY.failed_generic : COPY.degraded_generic);
}

/**
 * Классифицировать авторитетный Rust startup-label в вид для UI.
 *
 * Роутинг решён владельцем: `degraded:not_found` и `degraded:port_occupied`
 * показываются КРАСНЫМИ (нужны действия пользователя), несмотря на префикс
 * `degraded:` в протоколе. Любой неизвестный non-null label — красный
 * `protocol_error`: UI не понимает протокол и говорит об этом честно, вместо
 * того чтобы прятать возможно сломанное приложение за сплэшем.
 */
export function classifyStartup(label: string | null): StartupView {
  if (label === null || BOOTING.has(label)) {
    return { kind: "booting", reason: "booting", title: "", body: "" };
  }
  if (label === "python_ready") {
    return { kind: "ready", reason: "ready", title: "", body: "" };
  }
  if (RED.has(label)) {
    const reason = label === "failed" ? "generic" : label.slice(label.indexOf(":") + 1);
    return { kind: "failed", reason, ...copyFor(reason, "failed") };
  }
  if (AMBER.has(label)) {
    const reason = label.slice(label.indexOf(":") + 1);
    return { kind: "degraded", reason, ...copyFor(reason, "degraded") };
  }
  return { kind: "failed", reason: "protocol_error", ...COPY.protocol_error };
}
