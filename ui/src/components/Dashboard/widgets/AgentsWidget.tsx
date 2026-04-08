import { useAgentStore } from "../../../stores/agentStore";

export function AgentsWidget() {
  const agents = useAgentStore((s) => s.agents);
  const running = agents.filter((a) => a.status === "running").length;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Agents</div>
      <div className="text-3xl font-bold text-sky-400">{running}</div>
      <div className="text-xs text-gray-500 mt-1">{agents.length} registered</div>
    </div>
  );
}
