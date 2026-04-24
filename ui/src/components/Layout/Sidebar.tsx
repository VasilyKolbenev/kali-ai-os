import { useAppStore } from "../../stores/appStore";
import { ModeSelector } from "./ModeSelector";

export function Sidebar() {
  const kernelConnected = useAppStore((s) => s.kernelConnected);

  return (
    <aside className="w-[60px] h-screen flex flex-col items-center py-5 gap-3 relative z-10"
      style={{
        background: "var(--j-surface)",
        borderRight: "1px solid var(--j-border)",
      }}
    >
      {/* Connection indicator */}
      <div className="relative w-8 h-8 rounded-full flex items-center justify-center"
        style={{ background: "var(--j-surface)" }}>
        <div className={`w-2.5 h-2.5 rounded-full ${kernelConnected ? "status-online" : ""}`}
          style={{
            background: kernelConnected ? "var(--j-green)" : "var(--j-red)",
            boxShadow: kernelConnected
              ? "0 0 8px color-mix(in srgb, var(--j-green) 40%, transparent)"
              : "0 0 8px color-mix(in srgb, var(--j-red) 40%, transparent)",
          }}
        />
      </div>

      {/* KALI wordmark */}
      <div className="mt-2 mono text-[8px] tracking-[3px] uppercase"
        style={{ color: "var(--j-text-muted)", writingMode: "vertical-rl", letterSpacing: "4px" }}>
        KALI
      </div>

      <div className="flex-1" />
      <ModeSelector />
    </aside>
  );
}
