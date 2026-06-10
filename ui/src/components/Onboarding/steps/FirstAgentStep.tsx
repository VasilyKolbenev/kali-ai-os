import { useState } from "react";
import { useOnboardingStore } from "../../../stores/onboardingStore";
import { builderApi } from "../../../api/builder";
import { FadeSlideUp } from "../../../motion";
import { HexFrame } from "../../hud";

type AgentState = "idle" | "creating" | "ready" | "error";

const STARTER_EXAMPLES = [
  "напомни пить воду каждые 2 часа",
  "веди дневник настроения вечером",
  "считай выпитые чашки кофе за день",
  "напоминай делать зарядку каждое утро",
  "уведоми, когда пора сделать перерыв",
];

export function FirstAgentStep() {
  const advance = useOnboardingStore((s) => s.advance);
  const setSession = useOnboardingStore((s) => s.setFirstAgentSession);
  const [text, setText] = useState("");
  const [state, setState] = useState<AgentState>("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function startAgent(request: string) {
    if (!request.trim()) return;
    setState("creating");
    setMessage(null);
    try {
      const res = await builderApi.start(request);
      setSession(res.session_id);
      setMessage(res.question);
      setState("ready");
      setTimeout(() => advance(), 1500);
    } catch (e) {
      setState("error");
      const raw = e instanceof Error ? e.message : "";
      setMessage(
        raw.includes("pilot scope") || raw.includes("intent: agent")
          ? "Пока я делаю простые навыки — напоминания, трекеры, дневники. Опиши задачу попроще или нажми «Пропустить»."
          : "Не получилось создать прямо сейчас. Попробуй другой пример или пропусти.",
      );
    }
  }

  return (
    <FadeSlideUp>
      <div className="flex flex-col items-center gap-6 max-w-2xl w-full">
        <h2
          style={{
            fontSize: "var(--j-text-xl)",
            color: "var(--j-text)",
            textAlign: "center",
          }}
        >
          Давай сделаем первого агента
        </h2>
        <p
          style={{
            color: "var(--j-text-dim)",
            textAlign: "center",
            maxWidth: "480px",
          }}
        >
          Выбери пример или опиши свою задачу
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "var(--j-space-2)",
            width: "100%",
          }}
        >
          {STARTER_EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setText(ex);
                startAgent(ex);
              }}
              disabled={state === "creating"}
              style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
            >
              <HexFrame>
                <div
                  style={{
                    padding: "var(--j-space-3)",
                    textAlign: "center",
                    color: "var(--j-text)",
                    fontSize: "var(--j-text-sm)",
                  }}
                >
                  {ex}
                </div>
              </HexFrame>
            </button>
          ))}
        </div>

        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Или: что хочешь автоматизировать?"
          disabled={state === "creating"}
          onKeyDown={(e) => {
            if (e.key === "Enter") startAgent(text);
          }}
          style={{
            width: "100%",
            maxWidth: "520px",
            padding: "var(--j-space-3) var(--j-space-4)",
            background: "var(--j-surface)",
            border: "1px solid var(--j-border)",
            borderRadius: "var(--j-radius-md)",
            color: "var(--j-text)",
            fontFamily: "var(--j-font-mono)",
          }}
        />

        <button
          onClick={() => startAgent(text)}
          disabled={!text.trim() || state === "creating"}
          style={{
            padding: "var(--j-space-3) var(--j-space-6)",
            background:
              state === "ready"
                ? "color-mix(in srgb, var(--j-success) 20%, transparent)"
                : "color-mix(in srgb, var(--j-cyan) 15%, transparent)",
            border: `1px solid ${
              state === "ready" ? "var(--j-success)" : "var(--j-border-glow)"
            }`,
            borderRadius: "var(--j-radius-md)",
            color: state === "ready" ? "var(--j-success)" : "var(--j-cyan)",
            fontFamily: "var(--j-font-mono)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
            cursor: "pointer",
            fontSize: "var(--j-text-sm)",
          }}
        >
          {state === "creating"
            ? "Создаю..."
            : state === "ready"
              ? "✓ Агент готов"
              : "Создать агента"}
        </button>

        {message && (
          <div
            style={{
              color: state === "error" ? "var(--j-danger)" : "var(--j-text-dim)",
              fontSize: "var(--j-text-sm)",
              textAlign: "center",
              maxWidth: "480px",
            }}
          >
            {message}
          </div>
        )}

        <button
          onClick={() => advance()}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--j-text-muted)",
            cursor: "pointer",
            fontSize: "var(--j-text-xs)",
            letterSpacing: "var(--j-tracking-wide)",
            textTransform: "uppercase",
          }}
        >
          Пропустить — создам потом
        </button>
      </div>
    </FadeSlideUp>
  );
}
