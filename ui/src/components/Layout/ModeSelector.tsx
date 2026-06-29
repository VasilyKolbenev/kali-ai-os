import { useAppStore, type AppMode } from "../../stores/appStore";
import { motion } from "framer-motion";

// Deliberately minimal for the non-tech audience — everything removed from
// here stays reachable from inside these surfaces or by voice: Сводка absorbs
// Активность + живые виджеты Канваса; Мастерская (Мои · Витрина · Сообщество)
// absorbs Агенты and hosts «Создать голосом»; Ночной режим becomes a state.
const modes: { id: AppMode; label: string; icon: string; devOnly?: boolean }[] = [
  { id: "focus", label: "Джарвис", icon: "⦿" },
  { id: "dashboard", label: "Сводка", icon: "◫" },
  { id: "store", label: "Мастерская", icon: "▦" },
  { id: "pair", label: "Подключить телефон", icon: "▢" },
  { id: "settings", label: "Настройки", icon: "⚙" },
  { id: "showcase", label: "Showcase", icon: "◈", devOnly: true },
];

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
