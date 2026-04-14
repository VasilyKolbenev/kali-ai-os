import { useAgentStore } from "../../../stores/agentStore";

export function AgentsWidget() {
  const agents = useAgentStore((s) => s.agents);
  const running = agents.filter((a) => a.status === "running").length;
  return (
    <div className="glass p-5">
      <div className="mono text-[10px] tracking-[2px] uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>АГЕНТЫ</div>
      <div className="flex items-baseline gap-1">
        <span className="mono text-3xl font-light glow-text" style={{ color: "var(--j-cyan)" }}>{running}</span>
        <span className="mono text-[10px]" style={{ color: "var(--j-text-muted)" }}>онлайн</span>
      </div>
      <div className="mono text-[10px] mt-2" style={{ color: "var(--j-text-muted)" }}>{agents.length} зарег.</div>
    </div>
  );
}
