import { useAppStore } from "./stores/appStore";
import { useWebSocket } from "./api/websocket";
import { Avatar } from "./components/Avatar/Avatar";
import { Dashboard } from "./components/Dashboard/Dashboard";
import { AgentPanel } from "./components/AgentPanel/AgentPanel";
import { Nightstand } from "./components/Nightstand/Nightstand";
import { Sidebar } from "./components/Layout/Sidebar";
import { VoiceVisualizer } from "./components/VoiceVisualizer/VoiceVisualizer";

export default function App() {
  const mode = useAppStore((s) => s.mode);
  useWebSocket();

  return (
    <div className="flex h-screen w-screen bg-gray-950">
      <Sidebar />
      <main className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
        {mode === "focus" && (
          <div className="flex flex-col items-center gap-8">
            <Avatar />
            <VoiceVisualizer />
          </div>
        )}
        {mode === "dashboard" && <Dashboard />}
        {mode === "agents" && <AgentPanel />}
        {mode === "nightstand" && <Nightstand />}
      </main>
    </div>
  );
}
