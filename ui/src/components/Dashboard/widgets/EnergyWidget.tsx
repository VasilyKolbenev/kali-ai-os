import { useDashboardStore } from "../../../stores/dashboardStore";

export function EnergyWidget() {
  const data = useDashboardStore((s) => s.widgets.energy) as { calories: number } | undefined;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Energy</div>
      <div className="text-3xl font-bold text-red-400">{data?.calories?.toLocaleString() ?? "—"}</div>
      <div className="text-xs text-gray-500 mt-1">kcal</div>
    </div>
  );
}
