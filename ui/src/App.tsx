import { useEffect, useState } from "react";
import { useAppStore } from "./stores/appStore";
import { useWebSocket } from "./api/websocket";
import { useOnboardingGate } from "./hooks/useOnboardingGate";
import { Avatar } from "./components/Avatar/Avatar";
import { Dashboard } from "./components/Dashboard/Dashboard";
import { AgentStore } from "./components/AgentStore/AgentStore";
import { Settings } from "./components/Settings/Settings";
import { PairPhone } from "./components/Pairing/PairPhone";
import { VoiceBuilderScreen } from "./components/VoiceBuilder/VoiceBuilderScreen";
import { Showcase } from "./components/Showcase/Showcase";
import { OnboardingRoot } from "./components/Onboarding/OnboardingRoot";
import { Sidebar } from "./components/Layout/Sidebar";
import { VoiceVisualizer } from "./components/VoiceVisualizer/VoiceVisualizer";
import { ChatInput } from "./components/Chat/ChatInput";
import { AnimatePresence, motion } from "framer-motion";

/** True only after the kernel has been unreachable for a few seconds —
    avoids flashing the banner during normal startup/reconnect blips. */
function useKernelOffline(graceMs = 3000): boolean {
  const connected = useAppStore((s) => s.kernelConnected);
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if (connected) {
      setOffline(false);
      return;
    }
    const timer = setTimeout(() => setOffline(true), graceMs);
    return () => clearTimeout(timer);
  }, [connected, graceMs]);
  return offline;
}

export default function App() {
  const mode = useAppStore((s) => s.mode);
  useWebSocket();
  const { loading: onboardingLoading, gated: onboardingGated, slow } = useOnboardingGate();
  const kernelOffline = useKernelOffline();

  if (onboardingLoading) {
    return (
      <div
        className="w-full h-screen flex flex-col items-center justify-center gap-4"
        style={{ background: "var(--j-bg)", color: "var(--j-text-dim)" }}
      >
        <motion.div
          animate={{ opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          className="glow-text text-lg tracking-widest uppercase font-semibold"
        >
          Джарвис запускается…
        </motion.div>
        {slow && (
          <div className="text-xs text-center max-w-sm" style={{ color: "var(--j-text-muted)" }}>
            Первый запуск загружает голосовые модели — это может занять минуту.
            Если совсем долго, перезапусти приложение.
          </div>
        )}
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
          background:
            "radial-gradient(ellipse 70% 60% at 50% -10%, rgba(168, 85, 247, 0.08) 0%, rgba(0, 212, 255, 0.04) 40%, transparent 80%)",
        }}
        transition={{ duration: 1.5, ease: "easeInOut" }}
      />

      <Sidebar />

      {/* Kernel connectivity — plain words instead of raw fetch errors */}
      {kernelOffline && (
        <div
          className="fixed top-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl
            text-sm flex items-center gap-2 border backdrop-blur-md"
          style={{
            color: "var(--j-amber, #f59e0b)",
            borderColor: "color-mix(in srgb, var(--j-amber, #f59e0b) 40%, transparent)",
            background: "rgba(0,0,0,0.6)",
          }}
        >
          <span className="w-2 h-2 rounded-full bg-current animate-pulse" />
          Джарвис просыпается — восстанавливаю связь… Если это надолго, перезапусти приложение.
        </div>
      )}

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
            {mode === "store" && <AgentStore />}
            {mode === "builder" && <VoiceBuilderScreen />}
            {mode === "settings" && <Settings />}
            {mode === "pair" && <PairPhone />}
            {mode === "showcase" && <Showcase />}
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}
