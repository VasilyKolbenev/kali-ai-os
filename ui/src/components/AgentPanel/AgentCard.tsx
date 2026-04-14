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

export function AgentCard({ agent }: Props) {
  const updateAgent = useAgentStore((s) => s.updateAgent);
  const isRunning = agent.status === "running";
  const hint = AGENT_HINTS[agent.name];

  const toggle = async () => {
    try {
      if (isRunning) {
        await api.unloadAgent(agent.name);
        updateAgent(agent.name, "stopped");
      } else {
        await api.loadAgent(agent.name);
        updateAgent(agent.name, "running");
      }
    } catch (e) { console.error("Agent toggle failed:", e); }
  };

  return (
    <div className="glass p-4 flex items-center gap-4">
      <div className="w-2 h-2 rounded-full flex-shrink-0"
        style={{
          background: isRunning ? "var(--j-green)" : "rgba(255,255,255,0.1)",
          boxShadow: isRunning ? "0 0 8px rgba(0,230,118,0.3)" : "none",
        }}
      />
      <div className="flex-1 min-w-0">
        <div className="mono text-sm font-medium" style={{ color: "var(--j-text)" }}>{agent.name}</div>
        {agent.description && (
          <div className="text-xs truncate mt-0.5" style={{ color: "var(--j-text-muted)" }}>{agent.description}</div>
        )}
        {hint && (
          <div className="text-[10px] mt-1 italic" style={{ color: "var(--j-cyan-dim, rgba(0,212,255,0.4))" }}>{hint}</div>
        )}
      </div>
      <button
        onClick={toggle}
        className="mono text-[10px] tracking-wider uppercase px-3 py-1.5 rounded-lg transition-all duration-300"
        style={{
          background: isRunning ? "rgba(255, 61, 87, 0.08)" : "rgba(0, 230, 118, 0.08)",
          color: isRunning ? "var(--j-red)" : "var(--j-green)",
          border: `1px solid ${isRunning ? "rgba(255, 61, 87, 0.15)" : "rgba(0, 230, 118, 0.15)"}`,
        }}
      >
        {isRunning ? "Stop" : "Start"}
      </button>
    </div>
  );
}
