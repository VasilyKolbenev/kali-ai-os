import { useEffect } from "react";
import { useDashboardStore } from "../../stores/dashboardStore";
import { useAppStore } from "../../stores/appStore";
import { useChatStore } from "../../stores/chatStore";
import { api } from "../../api/client";
import type { AppMode } from "../../stores/appStore";
import { SleepWidget } from "./widgets/SleepWidget";
import { TasksWidget } from "./widgets/TasksWidget";
import { CalendarWidget } from "./widgets/CalendarWidget";
import { SpendingWidget } from "./widgets/SpendingWidget";
import { EnergyWidget } from "./widgets/EnergyWidget";
import { AgentsWidget } from "./widgets/AgentsWidget";
import { WeatherWidget } from "./widgets/WeatherWidget";
import { ActivityWidget } from "./widgets/ActivityWidget";
import { CanvasSection } from "../Canvas/Canvas";
import { motion } from "framer-motion";

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.1 }
  }
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { type: "spring", bounce: 0.4 } }
};

export function Dashboard() {
  const updateWidget = useDashboardStore((s) => s.updateWidget);
  const setMode = useAppStore((s) => s.setMode);
  const setPendingMessage = useChatStore((s) => s.setPendingMessage);

  const openChat = (query: string) => {
    setPendingMessage(query);
    setMode("focus" as AppMode);
  };

  useEffect(() => {
    async function fetchLiveData() {
      // Agents widget
      try {
        const running = await api.runningAgents();
        updateWidget("agents", { running: running.length });
      } catch {
        // kernel not running — keep previous data
      }

      // Tasks widget
      try {
        const taskData = await api.executeAgentTool("tasks", "get_summary") as {
          total?: number; done?: number; pending?: number;
        };
        updateWidget("tasks", { done: taskData.done ?? 0, total: taskData.total ?? 0 });
      } catch {
        // agent not running — keep previous data
      }

      // Calendar widget
      try {
        const calData = await api.executeAgentTool("calendar", "get_events", { date: "today" }) as {
          events?: Array<{ title?: string; start?: string }>;
        };
        const events = calData.events ?? [];
        updateWidget("calendar", {
          next: events[0]?.title ?? "Нет событий",
          time: events[0]?.start ?? "",
        });
      } catch {
        // agent not running — keep previous data
      }

      // Weather widget
      try {
        // City is intentionally omitted — the weather agent applies its own
        // server-side default rather than hardcoding a location in the UI.
        const wx = await api.executeAgentTool("weather", "get_weather") as {
          temperature_c?: number; condition?: string;
        };
        updateWidget("weather", { temp_c: wx.temperature_c, condition: wx.condition });
      } catch {
        // agent not running — keep previous data
      }

      // Life dashboard: sleep, spending, energy
      try {
        const lifeData = await api.executeAgentTool("life-dashboard", "get_daily_summary") as {
          sleep_hours?: number | null;
          sleep_hrv?: number | null;
          total_spending?: number;
          total_calories?: number;
        };
        updateWidget("sleep", { hours: lifeData.sleep_hours ?? null, hrv: lifeData.sleep_hrv ?? null });
        updateWidget("spending", { amount: lifeData.total_spending ?? 0 });
        updateWidget("energy", { calories: lifeData.total_calories ?? 0 });
      } catch {
        // life-dashboard not running — keep previous data
      }
    }

    fetchLiveData();
    const interval = setInterval(fetchLiveData, 30000);
    return () => clearInterval(interval);
  }, [updateWidget]);

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-baseline gap-3 mb-8">
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>Сводка</h2>
          <span className="mono text-[10px] tracking-widest uppercase" style={{ color: "var(--j-text-muted)" }}>В реальном времени</span>
        </div>
        <motion.div 
          className="grid grid-cols-2 lg:grid-cols-3 gap-4"
          variants={container}
          initial="hidden"
          animate="show"
        >
          <motion.div
            variants={item}
            onClick={() => openChat("покажи статистику сна")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <SleepWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => openChat("события сегодня")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <CalendarWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => openChat("покажи задачи")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <TasksWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => openChat("покажи расходы")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <SpendingWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => openChat("покажи калории за сегодня")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <EnergyWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => setMode("store" as AppMode)}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <AgentsWidget />
          </motion.div>
          <motion.div
            variants={item}
            onClick={() => openChat("какая погода?")}
            className="cursor-pointer hover:scale-[1.02] transition-transform duration-200"
          >
            <WeatherWidget />
          </motion.div>
          <motion.div variants={item}>
            <ActivityWidget />
          </motion.div>
        </motion.div>

        {/* Живые виджеты Джарвиса (бывший Канвас) — появляются по голосовой
            команде, напр. «покажи расходы графиком» */}
        <div className="mt-8">
          <CanvasSection hideWhenEmpty />
        </div>
      </div>
    </div>
  );
}
