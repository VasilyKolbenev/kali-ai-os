import { useDashboardStore } from "../../../stores/dashboardStore";

export function SpendingWidget() {
  const data = useDashboardStore((s) => s.widgets.spending) as { amount: number; currency: string } | undefined;
  return (
    <div className="bg-gray-900/60 border border-gray-800 rounded-2xl p-5">
      <div className="text-sm text-gray-400 mb-1">Spent</div>
      <div className="text-3xl font-bold text-orange-400">{data?.currency}{data?.amount ?? 0}</div>
    </div>
  );
}
