import { useAppStore, type AppMode } from "../../stores/appStore";

const modes: { id: AppMode; label: string; icon: string }[] = [
  { id: "focus", label: "Focus", icon: "\u29BF" },
  { id: "dashboard", label: "Dash", icon: "\u25EB" },
  { id: "agents", label: "Agents", icon: "\u2B21" },
  { id: "nightstand", label: "Night", icon: "\u263E" },
  { id: "store", label: "Store", icon: "\u25A6" },
];

export function ModeSelector() {
  const current = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);

  return (
    <div className="flex flex-col gap-1.5">
      {modes.map((m) => {
        const active = current === m.id;
        return (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            title={m.label}
            className="w-9 h-9 rounded-xl flex items-center justify-center text-sm transition-all duration-300 relative"
            style={{
              background: active ? "rgba(0, 212, 255, 0.1)" : "transparent",
              color: active ? "var(--j-cyan)" : "rgba(255,255,255,0.2)",
              boxShadow: active ? "0 0 12px rgba(0, 212, 255, 0.1), inset 0 0 12px rgba(0, 212, 255, 0.05)" : "none",
              border: active ? "1px solid rgba(0, 212, 255, 0.2)" : "1px solid transparent",
            }}
          >
            {m.icon}
          </button>
        );
      })}
    </div>
  );
}
