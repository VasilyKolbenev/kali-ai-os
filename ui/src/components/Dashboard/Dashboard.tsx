import { SleepWidget } from "./widgets/SleepWidget";
import { TasksWidget } from "./widgets/TasksWidget";
import { CalendarWidget } from "./widgets/CalendarWidget";
import { SpendingWidget } from "./widgets/SpendingWidget";
import { EnergyWidget } from "./widgets/EnergyWidget";
import { AgentsWidget } from "./widgets/AgentsWidget";

export function Dashboard() {
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
