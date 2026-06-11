import { useEffect, useState } from "react";
import { Check, ShieldAlert, X } from "lucide-react";
import { api } from "../../../api/client";
import type { AuditRecord } from "../../../api/types";

/** Compact «Что делал Джарвис» feed (absorbs the former Активность tab). */
export function ActivityWidget() {
  const [records, setRecords] = useState<AuditRecord[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await api.sandboxAudit({ hours: 24, limit: 5 });
        if (!cancelled) setRecords(res.results || []);
      } catch {
        /* kernel not running — keep previous */
      }
    };
    void load();
    const interval = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <div className="glass p-5 h-full">
      <div className="mono text-[10px] tracking-widest uppercase mb-3" style={{ color: "var(--j-text-muted)" }}>
        Что делал Джарвис
      </div>
      {records.length === 0 ? (
        <div className="text-sm" style={{ color: "var(--j-text-dim)" }}>
          Пока тихо
        </div>
      ) : (
        <div className="space-y-1.5">
          {records.map((r, i) => (
            <div key={i} className="flex items-center gap-2 text-xs" style={{ color: "var(--j-text-dim)" }}>
              {r.status === "ok" && <Check className="w-3 h-3 shrink-0 text-[var(--j-green)]" />}
              {r.status === "denied" && <ShieldAlert className="w-3 h-3 shrink-0 text-[var(--j-amber,#f59e0b)]" />}
              {r.status === "error" && <X className="w-3 h-3 shrink-0 text-red-400" />}
              <span className="truncate">
                {r.agent}: {r.action}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
