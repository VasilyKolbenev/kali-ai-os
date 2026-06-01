import { useAppStore, type AppMode } from "../../stores/appStore";

const modes: { id: AppMode; label: string; icon: string; devOnly?: boolean }[] = [
  { id: "focus", label: "Focus", icon: "\u29BF" },
  { id: "dashboard", label: "Dash", icon: "\u25EB" },
  { id: "agents", label: "Agents", icon: "\u2B21" },
  { id: "nightstand", label: "Night", icon: "\u263E" },
  { id: "store", label: "Store", icon: "\u25A6" },
  { id: "activity", label: "Activity", icon: "\u25F0" },
  { id: "builder", label: "Builder", icon: "\u2756" },
  { id: "canvas", label: "Canvas", icon: "\u25A3" }, // unicode square with cross or similar (e.g., 🎨 "\uD83C\uDFA8" but we use monochrome symbols, so let's use "\u25A3" square with dot or similar)
  { id: "settings", label: "Settings", icon: "\u2699" },
  { id: "showcase", label: "Showcase", icon: "\u25C8", devOnly: true },
];

import { motion } from "framer-motion";

export function ModeSelector() {
  const current = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const visibleModes = modes.filter((m) => !m.devOnly || import.meta.env.DEV);

  return (
    <div className="flex flex-col gap-2">
      {visibleModes.map((m) => {
        const active = current === m.id;
        return (
          <button
            key={m.id}
            onClick={() => setMode(m.id)}
            title={m.label}
            className="w-10 h-10 rounded-2xl flex items-center justify-center text-[15px] transition-all duration-300 relative group"
            style={{
              color: active ? "white" : "rgba(255,255,255,0.3)",
            }}
          >
            {active && (
              <motion.div
                layoutId="activeModeBubble"
                className="absolute inset-0 rounded-2xl opacity-90"
                style={{ background: "var(--j-gradient-primary)" }}
                initial={false}
                transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
              />
            )}
            <span className="relative z-10 group-hover:scale-110 transition-transform">
              {m.icon}
            </span>
          </button>
        );
      })}
    </div>
  );
}
