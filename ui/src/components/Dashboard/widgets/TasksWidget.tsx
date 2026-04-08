import { useDashboardStore } from "../../../stores/dashboardStore";

export function TasksWidget() {
  const data = useDashboardStore((s) => s.widgets.tasks) as { done: number; total: number } | undefined;
  const pct = data ? Math.round((data.done / data.total) * 100) : 0;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Tasks</div>
      <div className="text-3xl font-bold text-green-400">{data?.done ?? 0}/{data?.total ?? 0}</div>
      <div className="w-full bg-gray-800 rounded-full h-1.5 mt-2">
        <div className="bg-green-400 rounded-full h-1.5 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
