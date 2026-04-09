import { useAppStore } from "./stores/appStore";
import { useWebSocket } from "./api/websocket";
import { Avatar } from "./components/Avatar/Avatar";
import { Dashboard } from "./components/Dashboard/Dashboard";
import { AgentPanel } from "./components/AgentPanel/AgentPanel";
import { Nightstand } from "./components/Nightstand/Nightstand";
import { Sidebar } from "./components/Layout/Sidebar";
import { VoiceVisualizer } from "./components/VoiceVisualizer/VoiceVisualizer";
import { ChatInput } from "./components/Chat/ChatInput";

export default function App() {
  const mode = useAppStore((s) => s.mode);
  useWebSocket();

  return (
    <div className="flex h-screen w-screen" style={{ background: "var(--j-bg)" }}>
      {/* Ambient background glow */}
      <div
        className="fixed inset-0 pointer-events-none"
        style={{
          background: mode === "nightstand"
            ? "radial-gradient(ellipse 60% 40% at 50% 50%, rgba(0, 212, 255, 0.03) 0%, transparent 70%)"
            : "radial-gradient(ellipse 50% 50% at 50% 40%, rgba(0, 212, 255, 0.04) 0%, transparent 60%)",
        }}
      />

      <Sidebar />

      <main className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
        <div className="w-full h-full flex flex-col items-center justify-center fade-in-up" key={mode}>
          {mode === "focus" && (
            <div className="flex flex-col items-center w-full h-full justify-between py-8">
              <div className="flex-1 flex flex-col items-center justify-center gap-4">
                <div className="relative">
                  <div className="absolute inset-0 -m-8 rounded-full pulse-ring" style={{
                    background: "radial-gradient(circle, rgba(0, 212, 255, 0.08) 0%, transparent 70%)",
                  }} />
                  <Avatar />
                </div>
                <VoiceVisualizer />
              </div>
              <ChatInput />
            </div>
          )}
          {mode === "dashboard" && <Dashboard />}
          {mode === "agents" && <AgentPanel />}
          {mode === "nightstand" && <Nightstand />}
        </div>
      </main>
    </div>
  );
}
