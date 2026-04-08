import { useDashboardStore } from "../../../stores/dashboardStore";

export function SleepWidget() {
  const data = useDashboardStore((s) => s.widgets.sleep) as { hours: number; hrv: number } | undefined;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Sleep</div>
      <div className="text-3xl font-bold text-sky-400">{data?.hours ?? "—"}h</div>
      <div className="text-xs text-gray-500 mt-1">HRV {data?.hrv ?? "—"}</div>
    </div>
  );
}
