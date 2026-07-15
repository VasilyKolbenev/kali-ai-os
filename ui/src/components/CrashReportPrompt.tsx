import { useState } from "react";
import { resolveApiUrl } from "../api/endpoints";
import { useBackendLiveness } from "../hooks/useBackendLiveness";

type Phase = "idle" | "building" | "ready" | "error";
interface Report {
  path: string;
  text: string;
}
/** Сколько строк отчёта показываем в превью (юзер видит, что отправляет). */
const PREVIEW_LINES = 30;

/**
 * Opt-in промпт отчёта о сбое. Появляется, только когда Python-backend
 * уверенно мёртв; НИЧЕГО не собирает и не отправляет до клика. Сток локальный —
 * пользователь сам передаёт .txt. Спека: 2026-07-14-crash-optin-design.md
 */
export function CrashReportPrompt() {
  const backendDown = useBackendLiveness();
  const [phase, setPhase] = useState<Phase>("idle");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!backendDown) return null;

  const build = async () => {
    setPhase("building");
    setError(null);
    try {
      const res = await fetch(resolveApiUrl("/crash/report", "POST"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) throw new Error(String(res.status));
      setReport((await res.json()) as Report);
      setPhase("ready");
    } catch {
      setError("Не удалось собрать отчёт — открой папку данных KALI и передай логи вручную.");
      setPhase("error");
    }
  };

  const reveal = async () => {
    try {
      await fetch(resolveApiUrl("/crash/reveal", "POST"), { method: "POST" });
    } catch {
      /* путь показан текстом — юзер откроет вручную */
    }
  };

  const copy = async () => {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(report.text);
    } catch {
      // буфер недоступен (нет прав/окружения) — путь к файлу показан выше,
      // юзер откроет его сам; молча деградируем, не роняем промпт
    }
  };

  return (
    <div
      className="fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border p-4 shadow-lg text-sm"
      style={{
        background: "var(--j-surface, #111)",
        borderColor: "var(--j-border, #333)",
        color: "var(--j-text, #eee)",
      }}
      role="status"
    >
      {phase === "ready" && report ? (
        <>
          <div className="font-semibold">Отчёт готов</div>
          <div className="mt-1 break-all" style={{ color: "var(--j-text-dim, #aaa)" }}>
            {report.path}
          </div>
          <details className="mt-2">
            <summary className="cursor-pointer" style={{ color: "var(--j-text-dim, #aaa)" }}>
              Что внутри
            </summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-xs">
              {report.text.split("\n").slice(0, PREVIEW_LINES).join("\n")}
            </pre>
          </details>
          <div className="mt-2 flex items-center gap-2">
            <button
              className="rounded-lg px-3 py-1 font-medium"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              onClick={() => void reveal()}
            >
              Открыть папку
            </button>
            <button
              className="px-2 py-1"
              style={{ color: "var(--j-text-dim, #aaa)" }}
              onClick={() => void copy()}
            >
              Копировать
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="font-semibold">Похоже, ядро аварийно остановилось</div>
          <div className="mt-1" style={{ color: "var(--j-text-dim, #aaa)" }}>
            {phase === "error"
              ? error
              : "Подготовить отчёт для разработчика, чтобы это починить? Отчёт сохранится файлом — отправишь его сам."}
          </div>
          <div className="mt-2">
            <button
              className="rounded-lg px-3 py-1 font-medium disabled:opacity-50"
              style={{ background: "var(--j-accent, #2563eb)", color: "#fff" }}
              disabled={phase === "building"}
              onClick={() => void build()}
            >
              {phase === "building" ? "Собираю…" : "Подготовить отчёт"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
