import { useAppStore } from "./stores/appStore";
import { useWebSocket } from "./api/websocket";
import { useOnboardingGate } from "./hooks/useOnboardingGate";
import { Avatar } from "./components/Avatar/Avatar";
import { Dashboard } from "./components/Dashboard/Dashboard";
import { AgentPanel } from "./components/AgentPanel/AgentPanel";
import { Nightstand } from "./components/Nightstand/Nightstand";
import { AgentStore } from "./components/AgentStore/AgentStore";
import { SandboxActivity } from "./components/SandboxActivity/SandboxActivity";
import { Settings } from "./components/Settings/Settings";
import { VoiceBuilderScreen } from "./components/VoiceBuilder/VoiceBuilderScreen";
import { Showcase } from "./components/Showcase/Showcase";
import { OnboardingRoot } from "./components/Onboarding/OnboardingRoot";
import { Canvas } from "./components/Canvas/Canvas";
import { Sidebar } from "./components/Layout/Sidebar";
import { VoiceVisualizer } from "./components/VoiceVisualizer/VoiceVisualizer";
import { ChatInput } from "./components/Chat/ChatInput";
import { AnimatePresence, motion } from "framer-motion";

export default function App() {
  const mode = useAppStore((s) => s.mode);
  useWebSocket();
  const { loading: onboardingLoading, gated: onboardingGated } = useOnboardingGate();

  if (onboardingLoading) {
    return (
      <div
        className="w-full h-screen flex items-center justify-center"
        style={{ background: "var(--j-bg)", color: "var(--j-text-dim)" }}
      >
        <motion.div
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="glow-text text-lg tracking-widest uppercase font-semibold"
        >
          Loading KALI...
        </motion.div>
      </div>
    );
  }
  if (onboardingGated) {
    return <OnboardingRoot />;
  }

  return (
    <div className="flex h-screen w-screen" style={{ background: "var(--j-bg)" }}>
      {/* Dynamic ambient background glow */}
      <motion.div
        className="fixed inset-0 pointer-events-none"
        animate={{
          background: mode === "nightstand"
            ? "radial-gradient(ellipse 60% 40% at 50% 50%, rgba(0, 212, 255, 0.03) 0%, transparent 70%)"
            : "radial-gradient(ellipse 70% 60% at 50% -10%, rgba(168, 85, 247, 0.08) 0%, rgba(0, 212, 255, 0.04) 40%, transparent 80%)",
        }}
        transition={{ duration: 1.5, ease: "easeInOut" }}
      />

      <Sidebar />

      <main className="flex-1 flex flex-col items-center justify-center relative overflow-hidden">
        {/* mode="wait" deadlocks if a mode view contains a shared `layoutId`
            element that has moved (exit never completes -> blank screen), so
            keep layoutId out of the views below. */}
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            initial={{ opacity: 0, y: 15, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -15, scale: 0.98 }}
            transition={{ duration: 0.4, ease: [0.2, 0.8, 0.2, 1] }}
            className="w-full h-full flex flex-col items-center justify-center"
          >
            {mode === "focus" && (
              <div className="flex flex-col items-center w-full h-full justify-between py-8">
                <div className="flex-1 flex flex-col items-center justify-center gap-4">
                  <div className="relative">
                    <div className="absolute inset-0 -m-8 rounded-full pulse-ring" style={{
                      background: "radial-gradient(circle, rgba(0, 212, 255, 0.1) 0%, transparent 70%)",
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
            {mode === "store" && <AgentStore />}
            {mode === "activity" && <SandboxActivity />}
            {mode === "builder" && <VoiceBuilderScreen />}
            {mode === "canvas" && <Canvas />}
            {mode === "settings" && <Settings />}
            {mode === "showcase" && <Showcase />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
