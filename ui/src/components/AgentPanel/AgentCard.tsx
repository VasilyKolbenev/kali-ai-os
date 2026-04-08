import { api } from "../../api/client";
import { useAgentStore } from "../../stores/agentStore";

interface Props {
  agent: { name: string; status: string; description?: string };
}

export function AgentCard({ agent }: Props) {
  const updateAgent = useAgentStore((s) => s.updateAgent);
  const isRunning = agent.status === "running";

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
    <div className="bg-gray-900/60 border border-gray-800 rounded-xl p-4 flex items-center gap-4">
      <div className={`w-3 h-3 rounded-full ${isRunning ? "bg-green-400" : "bg-gray-600"}`} />
      <div className="flex-1">
        <div className="font-medium text-white">{agent.name}</div>
        {agent.description && <div className="text-xs text-gray-500">{agent.description}</div>}
      </div>
      <button
        onClick={toggle}
        className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${isRunning ? "bg-red-400/20 text-red-400 hover:bg-red-400/30" : "bg-green-400/20 text-green-400 hover:bg-green-400/30"}`}
      >
        {isRunning ? "Stop" : "Start"}
      </button>
    </div>
  );
}
