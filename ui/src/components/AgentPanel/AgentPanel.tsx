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
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-baseline gap-3 mb-8">
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>Agents</h2>
          <span className="mono text-[10px] tracking-widest uppercase" style={{ color: "var(--j-text-muted)" }}>{agents.length} total</span>
        </div>
        <div className="grid gap-2 stagger">
          {agents.length === 0 && (
            <p className="text-center py-12" style={{ color: "var(--j-text-muted)" }}>No agents registered</p>
          )}
          {agents.map((agent) => (
            <AgentCard key={agent.name} agent={agent} />
          ))}
        </div>
      </div>
    </div>
  );
}
