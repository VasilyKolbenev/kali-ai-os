import { useState } from "react";
import { api } from "../../api/client";
import { useAgentStore } from "../../stores/agentStore";

const AGENT_HINTS: Record<string, string> = {
  weather: "Напишите: 'какая погода?'",
  system: "Напишите: 'который час?'",
  tasks: "Напишите: 'покажи задачи'",
  calendar: "Напишите: 'события сегодня'",
  "life-dashboard": "Напишите: 'расходы' или 'сон'",
  email: "Напишите: 'проверь почту'",
  telegram: "Напишите: 'отправь в телеграм'",
  "smart-home": "Напишите: 'включи свет'",
  coding: "Напишите: 'объясни код'",
};

interface Props {
  agent: { name: string; status: string; description?: string };
}

type Feedback =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; msg: string }
  | { kind: "error"; msg: string };

export function AgentCard({ agent }: Props) {
  const updateAgent = useAgentStore((s) => s.updateAgent);
  const isRunning = agent.status === "running";
  const hint = AGENT_HINTS[agent.name];
  const [feedback, setFeedback] = useState<Feedback>({ kind: "idle" });

  const toggle = async () => {
    setFeedback({ kind: "loading" });
    try {
      if (isRunning) {
        await api.unloadAgent(agent.name);
        updateAgent(agent.name, "stopped");
        setFeedback({ kind: "success", msg: `✓ ${agent.name} остановлен` });
      } else {
        await api.loadAgent(agent.name);
        updateAgent(agent.name, "running");
        const tip = hint ? ` ${hint}` : "";
        setFeedback({ kind: "success", msg: `✓ ${agent.name} запущен.${tip}` });
      }
      setTimeout(() => setFeedback({ kind: "idle" }), 4000);
    } catch (e) {
      console.error("Agent toggle failed:", e);
      setFeedback({
        kind: "error",
        msg: `Ошибка: ${e instanceof Error ? e.message : String(e)}`,
      });
      setTimeout(() => setFeedback({ kind: "idle" }), 6000);
    }
  };

  const feedbackColor =
    feedback.kind === "success"
      ? "var(--j-green)"
      : feedback.kind === "error"
        ? "var(--j-red)"
        : "var(--j-text-muted)";

  return (
    <div className="glass p-4 flex flex-col gap-2">
      <div className="flex items-center gap-4">
        <div className="w-2 h-2 rounded-full flex-shrink-0"
          style={{
            background: isRunning ? "var(--j-green)" : "var(--j-surface-soft)",
            boxShadow: isRunning ? "0 0 8px var(--j-success-glow)" : "none",
          }}
        />
        <div className="flex-1 min-w-0">
          <div className="mono text-sm font-medium" style={{ color: "var(--j-text)" }}>{agent.name}</div>
          {agent.description && (
            <div className="text-xs truncate mt-0.5" style={{ color: "var(--j-text-muted)" }}>{agent.description}</div>
          )}
          {hint && (
            <div className="text-[10px] mt-1 italic" style={{ color: "var(--j-cyan-dim)" }}>{hint}</div>
          )}
        </div>
        <button
          onClick={toggle}
          disabled={feedback.kind === "loading"}
          className="mono text-[10px] tracking-wider uppercase px-3 py-1.5 rounded-lg transition-all duration-300 disabled:opacity-50"
          style={{
            background: isRunning ? "var(--j-danger-wash)" : "var(--j-success-wash)",
            color: isRunning ? "var(--j-red)" : "var(--j-green)",
            border: `1px solid ${isRunning ? "var(--j-danger-soft)" : "var(--j-success-soft)"}`,
          }}
        >
          {feedback.kind === "loading" ? "..." : isRunning ? "Stop" : "Start"}
        </button>
      </div>
      {(feedback.kind === "success" || feedback.kind === "error") && (
        <div className="text-xs pl-6 italic" style={{ color: feedbackColor }}>
          {feedback.msg}
        </div>
      )}
    </div>
  );
}
