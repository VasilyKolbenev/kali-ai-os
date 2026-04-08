import { SleepWidget } from "./widgets/SleepWidget";
import { TasksWidget } from "./widgets/TasksWidget";
import { CalendarWidget } from "./widgets/CalendarWidget";
import { SpendingWidget } from "./widgets/SpendingWidget";
import { EnergyWidget } from "./widgets/EnergyWidget";
import { AgentsWidget } from "./widgets/AgentsWidget";

export function Dashboard() {
  return (
    <div className="w-full h-full p-6 overflow-auto">
      <h2 className="text-2xl font-bold mb-6 text-gray-100">Dashboard</h2>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 max-w-4xl mx-auto">
        <SleepWidget />
        <CalendarWidget />
        <TasksWidget />
        <SpendingWidget />
        <EnergyWidget />
        <AgentsWidget />
      </div>
    </div>
  );
}
