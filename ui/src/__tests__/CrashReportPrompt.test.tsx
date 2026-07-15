import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CrashReportPrompt } from "../components/CrashReportPrompt";

function statusReply(alive: boolean) {
  return new Response(JSON.stringify({ backend_alive: alive }));
}
/** ДЛИННЕЕ, чем PREVIEW_LINES (30) — иначе полный текст и превью побайтово
 *  совпадают, и тест «Копировать» не отличит полный отчёт от обрезанного
 *  превью (проверено мутацией: на 2-строчной фикстуре он зелёный и при
 *  copy(preview)). Обрезка копии молча урезала бы диагностику. */
const REPORT_TEXT = `KALI crash report\n${Array.from({ length: 40 }, (_, i) => `line-${i}`).join("\n")}`;

function reportReply() {
  return new Response(
    JSON.stringify({ path: "C:\\KALI\\crash-reports\\crash-1.txt", text: REPORT_TEXT }),
  );
}

/** fetch-роутер: /crash/status → alive-флаг, /crash/report → отчёт. */
function stubFetch(alive: boolean, onReport?: () => void) {
  return vi.fn(async (url: string) => {
    if (String(url).includes("/crash/status")) return statusReply(alive);
    if (String(url).includes("/crash/report")) {
      onReport?.();
      return reportReply();
    }
    return new Response("{}");
  });
}

describe("CrashReportPrompt", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("не рендерится, пока backend жив", async () => {
    vi.stubGlobal("fetch", stubFetch(true));
    const { container } = render(<CrashReportPrompt />);
    await waitFor(() => expect(container.firstChild).toBeNull());
  });

  it("opt-in: /crash/report НЕ зовётся до клика", async () => {
    const onReport = vi.fn();
    vi.stubGlobal("fetch", stubFetch(false, onReport));
    render(<CrashReportPrompt />);
    await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    expect(onReport).not.toHaveBeenCalled();
  }, 25000);

  it("клик собирает отчёт и показывает путь + кнопки", async () => {
    vi.stubGlobal("fetch", stubFetch(false));
    const user = userEvent.setup();
    const { container } = render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    expect(await screen.findByText(/crash-1\.txt/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /открыть папку/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /копировать/i })).toBeInTheDocument();
    // Превью — ровно первые PREVIEW_LINES строк: ранние есть, поздние отрезаны.
    const preview = container.querySelector("pre");
    expect(preview?.textContent).toContain("line-0");
    expect(preview?.textContent).not.toContain("line-39");
  }, 25000);

  it("«Открыть папку» шлёт POST /crash/reveal БЕЗ пути в теле", async () => {
    const calls: string[] = [];
    let revealBody: BodyInit | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const u = String(url);
        calls.push(u);
        if (u.includes("/crash/status")) return statusReply(false);
        if (u.includes("/crash/report")) return reportReply();
        if (u.includes("/crash/reveal")) {
          revealBody = init?.body ?? null;
          return new Response(JSON.stringify({ status: "ok" }));
        }
        return new Response("{}");
      }),
    );
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    await user.click(await screen.findByRole("button", { name: /открыть папку/i }));
    await waitFor(() => expect(calls.some((u) => u.includes("/crash/reveal"))).toBe(true));
    // Ассертим ВНЕ fetch-стаба: брошенный внутри стаба AssertionError сожрал бы
    // `catch {}` в reveal(), и тест был бы зелёным при ЛЮБОМ теле (проверено
    // мутацией). Клиентский путь не передаём — сервер сам знает reports_dir.
    expect(revealBody).toBeNull();
  }, 25000);

  it("«Копировать» кладёт полный текст отчёта в буфер", async () => {
    const writeText = vi.fn(async () => {});
    vi.stubGlobal("fetch", stubFetch(false));
    // setup() ДО стаба navigator: userEvent вешает СВОЙ clipboard-стаб на
    // navigator и затёр бы наш, если бы шёл после (тест был бы ложно-красным).
    const user = userEvent.setup();
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    await user.click(await screen.findByRole("button", { name: /копировать/i }));
    // ПОЛНЫЙ текст, не превью: REPORT_TEXT длиннее PREVIEW_LINES, поэтому
    // регрессия до copy(preview) роняет этот assert.
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(REPORT_TEXT));
  }, 25000);

  it("ошибка сборки показывается честно", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).includes("/crash/status")) return statusReply(false);
        return new Response(JSON.stringify({ error: "disk full" }), { status: 500 });
      }),
    );
    const user = userEvent.setup();
    render(<CrashReportPrompt />);
    const btn = await screen.findByRole("button", { name: /подготовить отчёт/i }, { timeout: 20000 });
    await user.click(btn);
    expect(await screen.findByText(/не удалось собрать отчёт/i)).toBeInTheDocument();
  }, 25000);
});
