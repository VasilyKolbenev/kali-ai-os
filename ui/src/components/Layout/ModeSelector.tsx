import { useAppStore, type AppMode } from "../../stores/appStore";

const modes: { id: AppMode; icon: string; label: string }[] = [
  { id: "focus", icon: "◉", label: "Focus" },
  { id: "dashboard", icon: "▦", label: "Dashboard" },
  { id: "agents", icon: "⚙", label: "Agents" },
  { id: "nightstand", icon: "☽", label: "Night" },
];

export function ModeSelector() {
  const current = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);

  return (
    <div className="flex flex-col gap-2">
      {modes.map((m) => (
        <button
          key={m.id}
          onClick={() => setMode(m.id)}
          className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg transition-all
            ${current === m.id
              ? "bg-sky-400/20 text-sky-400"
              : "text-gray-500 hover:text-gray-300 hover:bg-gray-800"
            }`}
          title={m.label}
        >
          {m.icon}
        </button>
      ))}
    </div>
  );
}
