import { useDashboardStore } from "../../../stores/dashboardStore";

export function CalendarWidget() {
  const data = useDashboardStore((s) => s.widgets.calendar) as { next: string; time: string } | undefined;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Next</div>
      <div className="text-lg font-semibold text-white">{data?.next ?? "No events"}</div>
      <div className="text-xs text-gray-500 mt-1">{data?.time ?? ""}</div>
    </div>
  );
}
