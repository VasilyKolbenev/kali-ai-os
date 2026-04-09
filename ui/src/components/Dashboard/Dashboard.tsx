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
      try {
        const [running, _health] = await Promise.all([
          api.runningAgents(),
          api.health(),
        ]);
        updateWidget("agents", { running: running.length });
        // _health available for future widget updates
      } catch (e) {
        // Kernel may not be running — keep mock data
      }
    }
    fetchLiveData();
    const interval = setInterval(fetchLiveData, 10000);
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
