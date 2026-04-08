import { useEffect } from "react";
import { useAgentStore } from "../../stores/agentStore";
import { AgentCard } from "./AgentCard";
import { api } from "../../api/client";

export function AgentPanel() {
  const agents = useAgentStore((s) => s.agents);
  const setAgents = useAgentStore((s) => s.setAgents);

  useEffect(() => {
    api.agents().then((manifests) => {
      setAgents(manifests.map((m) => ({ name: m.name, status: "stopped", description: m.description })));
    }).catch(console.error);
  }, [setAgents]);

  return (
    <div className="w-full h-full p-6 overflow-auto">
      <h2 className="text-2xl font-bold mb-6 text-gray-100">Agents</h2>
      <div className="grid gap-3 max-w-2xl mx-auto">
        {agents.length === 0 && <p className="text-gray-500 text-center">No agents registered</p>}
        {agents.map((agent) => <AgentCard key={agent.name} agent={agent} />)}
      </div>
    </div>
  );
}
