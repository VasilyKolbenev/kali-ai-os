import { useAppStore } from "../../stores/appStore";
import { ModeSelector } from "./ModeSelector";

export function Sidebar() {
  const kernelConnected = useAppStore((s) => s.kernelConnected);

  return (
    <aside className="w-16 h-screen bg-gray-900/50 border-r border-gray-800 flex flex-col items-center py-4 gap-4">
      <div className="w-8 h-8 rounded-full bg-[var(--jarvis-blue)]/20 flex items-center justify-center">
        <div className={`w-3 h-3 rounded-full ${kernelConnected ? "bg-[var(--jarvis-green)]" : "bg-[var(--jarvis-red)]"}`} />
      </div>
      <div className="flex-1" />
      <ModeSelector />
    </aside>
  );
}
