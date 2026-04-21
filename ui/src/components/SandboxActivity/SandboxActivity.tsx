import { useEffect, useMemo, useState } from "react";
import {
  Activity as ActivityIcon, RefreshCw, Shield, AlertCircle,
  Check, X, Ban, Clock, Loader2,
} from "lucide-react";
import { api } from "../../api/client";
import type {
  AuditAgentStats, AuditRecord, AuditStatus, SandboxHealth,
} from "../../api/types";

const TIME_RANGES: { id: number; label: string }[] = [
  { id: 1, label: "1h" },
  { id: 24, label: "24h" },
  { id: 24 * 7, label: "7d" },
  { id: 24 * 30, label: "30d" },
];

const STATUS_FILTERS: { id: "" | AuditStatus; label: string }[] = [
  { id: "", label: "All" },
  { id: "ok", label: "OK" },
  { id: "denied", label: "Denied" },
  { id: "error", label: "Error" },
];

export function SandboxActivity() {
  const [hours, setHours] = useState(24);
  const [statusFilter, setStatusFilter] = useState<"" | AuditStatus>("");
  const [stats, setStats] = useState<AuditAgentStats[]>([]);
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [health, setHealth] = useState<SandboxHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    setLoading(true);
    setErr("");
    try {
      const [healthRes, statsRes, auditRes] = await Promise.all([
        api.sandboxHealth(),
        api.sandboxStats(hours),
        api.sandboxAudit({
          hours,
          status: statusFilter || undefined,
          limit: 200,
        }),
      ]);
      setHealth(healthRes);
      setStats(statsRes.results || []);
      setRecords(auditRes.results || []);
    } catch (e) {
      setErr((e as Error).message || "Failed to load activity");
      setStats([]);
      setRecords([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hours, statusFilter]);

  const totals = useMemo(() => {
    return stats.reduce(
      (acc, s) => ({
        total: acc.total + s.total,
        ok: acc.ok + s.ok_count,
        denied: acc.denied + s.denied_count,
        error: acc.error + s.error_count,
      }),
      { total: 0, ok: 0, denied: 0, error: 0 },
    );
  }, [stats]);

  return (
    <div className="w-full h-full p-8 overflow-auto">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-baseline gap-3 mb-6">
          <ActivityIcon className="w-5 h-5 text-[var(--j-cyan)]" />
          <h2 className="text-lg font-medium" style={{ color: "var(--j-text)" }}>
            Activity
          </h2>
          {health && <HealthBadges health={health} />}
          <button
            onClick={load}
            disabled={loading}
            className="ml-auto text-white/40 hover:text-white/80 transition disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        {/* Filter controls */}
        <div className="flex gap-4 mb-6 text-xs">
          <FilterGroup
            label="Period"
            options={TIME_RANGES.map((t) => ({ id: t.id, label: t.label }))}
            value={hours}
            onChange={(v) => setHours(v as number)}
          />
          <FilterGroup
            label="Status"
            options={STATUS_FILTERS.map((s) => ({ id: s.id, label: s.label }))}
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as "" | AuditStatus)}
          />
        </div>

        {/* Totals overview */}
        <div className="grid grid-cols-4 gap-3 mb-8">
          <StatCard label="Total calls" value={totals.total} color="var(--j-cyan)" />
          <StatCard
            label="Succeeded"
            value={totals.ok}
            color="var(--j-green)"
            icon={<Check className="w-3.5 h-3.5" />}
          />
          <StatCard
            label="Denied"
            value={totals.denied}
            color="var(--j-amber, #f59e0b)"
            icon={<Ban className="w-3.5 h-3.5" />}
          />
          <StatCard
            label="Errors"
            value={totals.error}
            color="var(--j-red, #ef4444)"
            icon={<AlertCircle className="w-3.5 h-3.5" />}
          />
        </div>

        {err && (
          <div className="glass p-4 mb-6 text-sm text-red-400 flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {err}
          </div>
        )}

        {/* Per-agent stats */}
        <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
          Per-agent usage
        </h3>
        <div className="grid gap-1.5 mb-8">
          {stats.length === 0 && !loading && (
            <div className="glass p-4 text-sm text-white/30">
              No activity in the selected period.
            </div>
          )}
          {stats.map((s) => (
            <AgentStatRow key={s.agent} stat={s} />
          ))}
        </div>

        {/* Recent audit log */}
        <h3 className="text-xs font-medium text-white/50 uppercase tracking-wider mb-3">
          Recent dispatches
        </h3>
        <div className="grid gap-1 stagger">
          {records.length === 0 && !loading && (
            <div className="glass p-4 text-sm text-white/30">
              No dispatches to show.
            </div>
          )}
          {records.map((r) => (
            <AuditRow key={r.id} record={r} />
          ))}
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------------

function FilterGroup<T extends string | number>({
  label, options, value, onChange,
}: {
  label: string;
  options: { id: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] tracking-widest uppercase text-white/30">
        {label}
      </span>
      <div className="flex gap-0.5 bg-white/[0.02] rounded p-0.5">
        {options.map((o) => {
          const active = o.id === value;
          return (
            <button
              key={String(o.id)}
              onClick={() => onChange(o.id)}
              className={`px-2.5 py-1 rounded text-[11px] transition
                ${active
                  ? "bg-[var(--j-cyan)]/15 text-[var(--j-cyan)]"
                  : "text-white/40 hover:text-white/70"}`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StatCard({
  label, value, color, icon,
}: {
  label: string;
  value: number;
  color: string;
  icon?: React.ReactNode;
}) {
  return (
    <div
      className="glass p-3 rounded"
      style={{ borderLeftColor: color, borderLeftWidth: 2 }}
    >
      <div className="flex items-center gap-1.5 text-[10px] tracking-widest uppercase text-white/40 mb-1">
        {icon}
        {label}
      </div>
      <div className="text-xl font-light" style={{ color }}>
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function HealthBadges({ health }: { health: SandboxHealth }) {
  const badges: { label: string; on: boolean }[] = [
    { label: "enforcer", on: health.enforcer_enabled },
    { label: "rate limit", on: health.rate_limiter_enabled },
    { label: "audit", on: health.audit_sink_enabled },
  ];
  return (
    <div className="flex items-center gap-1.5 ml-2">
      {badges.map((b) => (
        <span
          key={b.label}
          className="text-[9px] tracking-wider uppercase px-1.5 py-0.5 rounded"
          style={{
            color: b.on ? "var(--j-green)" : "var(--j-text-muted)",
            backgroundColor: b.on ? "rgba(0,230,118,0.08)" : "rgba(255,255,255,0.03)",
          }}
        >
          <Shield className="w-2.5 h-2.5 inline mr-0.5" />
          {b.label}
        </span>
      ))}
    </div>
  );
}

function AgentStatRow({ stat }: { stat: AuditAgentStats }) {
  const okRatio = stat.total > 0 ? stat.ok_count / stat.total : 1;
  return (
    <div className="glass p-3 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-sm truncate">{stat.agent}</div>
        <div className="flex gap-3 text-[11px] text-white/40 mt-0.5">
          <span>{stat.total} calls</span>
          {stat.avg_ms !== null && <span>{stat.avg_ms.toFixed(0)}ms avg</span>}
        </div>
      </div>
      {/* Bar chart: ok / denied / error proportions */}
      <div className="flex h-1.5 w-32 rounded-full overflow-hidden bg-white/5 shrink-0">
        <div style={{ width: `${okRatio * 100}%`, background: "var(--j-green)" }} />
        <div
          style={{
            width: `${(stat.denied_count / Math.max(1, stat.total)) * 100}%`,
            background: "var(--j-amber, #f59e0b)",
          }}
        />
        <div
          style={{
            width: `${(stat.error_count / Math.max(1, stat.total)) * 100}%`,
            background: "var(--j-red, #ef4444)",
          }}
        />
      </div>
      <div className="flex gap-2 text-[11px] shrink-0 w-36 justify-end">
        <span className="text-[var(--j-green)]">{stat.ok_count}</span>
        {stat.denied_count > 0 && (
          <span className="text-[var(--j-amber,#f59e0b)]">
            ⊘ {stat.denied_count}
          </span>
        )}
        {stat.error_count > 0 && (
          <span className="text-red-400">⚠ {stat.error_count}</span>
        )}
      </div>
    </div>
  );
}

function AuditRow({ record }: { record: AuditRecord }) {
  const when = new Date(record.timestamp * 1000);
  const timeStr = when.toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const dateStr = when.toLocaleDateString();

  let statusColor = "var(--j-green)";
  let StatusIcon = Check;
  if (record.status === "denied") {
    statusColor = "var(--j-amber, #f59e0b)";
    StatusIcon = Ban;
  } else if (record.status === "error") {
    statusColor = "var(--j-red, #ef4444)";
    StatusIcon = X;
  }

  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 rounded text-xs hover:bg-white/[0.02] transition"
      title={record.error || undefined}
    >
      <StatusIcon className="w-3.5 h-3.5 shrink-0" style={{ color: statusColor }} />
      <div className="flex-1 min-w-0 flex gap-2">
        <span className="text-white/80 font-medium shrink-0">
          {record.agent}
        </span>
        <span className="text-white/40 truncate">.{record.action}</span>
        {record.denied_reason && (
          <span
            className="text-[10px] tracking-wider uppercase px-1 py-0.5 rounded shrink-0"
            style={{ color: statusColor, backgroundColor: statusColor + "15" }}
          >
            {record.denied_reason}
          </span>
        )}
        {record.error && (
          <span className="text-red-400/70 truncate text-[10px]">
            {record.error}
          </span>
        )}
      </div>
      <span className="text-[10px] text-white/30 flex items-center gap-1 shrink-0">
        <Clock className="w-3 h-3" />
        {record.duration_ms}ms
      </span>
      <span className="text-[10px] text-white/30 shrink-0 mono">
        {timeStr}
      </span>
      <span className="text-[10px] text-white/20 shrink-0 mono w-16 text-right">
        {dateStr}
      </span>
    </div>
  );
}
