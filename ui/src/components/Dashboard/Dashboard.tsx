import { useEffect } from "react";
import { useDashboardStore } from "../../stores/dashboardStore";
import { api } from "../../api/client";
import { SleepWidget } from "./widgets/SleepWidget";
import { TasksWidget } from "./widgets/TasksWidget";
import { CalendarWidget } from "./widgets/CalendarWidget";
import { SpendingWidget } from "./widgets/SpendingWidget";
import { EnergyWidget } from "./widgets/EnergyWidget";
import { AgentsWidget } from "./widgets/AgentsWidget";

export function Dashboard() {
  const updateWidget = useDashboardStore((s) => s.updateWidget);

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
          next: events[0]?.title ?? "No events",
          time: events[0]?.start ?? "",
        });
      } catch {
        // agent not running — keep previous data
      }

      // Weather widget (stored in energy slot if no dedicated widget)
      try {
        const wx = await api.executeAgentTool("weather", "get_weather", { city: "Moscow" }) as {
          temp_c?: number; condition?: string;
        };
        updateWidget("weather", { temp_c: wx.temp_c, condition: wx.condition });
      } catch {
        // agent not running — keep previous data
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
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>Dashboard</h2>
          <span className="mono text-[10px] tracking-widest uppercase" style={{ color: "var(--j-text-muted)" }}>Live</span>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 stagger">
          <SleepWidget />
          <CalendarWidget />
          <TasksWidget />
          <SpendingWidget />
          <EnergyWidget />
          <AgentsWidget />
        </div>
      </div>
    </div>
  );
}
