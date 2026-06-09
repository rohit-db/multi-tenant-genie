import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Users, Activity, Timer, AlertTriangle } from "lucide-react";
import { api, type Tenant, type AuditRow } from "@/lib/api";

export function NumbersStrip() {
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const audit = useQuery({
    queryKey: ["audit", "stats"],
    queryFn: () => api.audit(500),
    refetchInterval: 8000,
  });

  const stats = useMemo(() => computeStats(tenants.data, audit.data), [
    tenants.data,
    audit.data,
  ]);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <NumberCard
        label="Active tenants"
        value={stats.activeTenants}
        icon={Users}
        tint="text-emerald-600"
      />
      <NumberCard
        label="Queries (last hr)"
        value={stats.queriesLastHour}
        icon={Activity}
        tint="text-indigo-600"
      />
      <NumberCard
        label="p95 latency"
        value={stats.p95LatencyMs == null ? "—" : `${stats.p95LatencyMs} ms`}
        icon={Timer}
        tint="text-slate-600"
      />
      <NumberCard
        label="Errors (last hr)"
        value={stats.errorsLastHour}
        icon={AlertTriangle}
        tint={stats.errorsLastHour > 0 ? "text-rose-600" : "text-slate-400"}
      />
    </div>
  );
}

function computeStats(tenants?: Tenant[], audit?: AuditRow[]) {
  const activeTenants =
    (tenants ?? []).filter((t) => t.status === "active").length;

  const oneHourAgo = Date.now() - 60 * 60 * 1000;
  const recent = (audit ?? []).filter((r) => {
    const t = Date.parse(r.created_at);
    return Number.isFinite(t) && t >= oneHourAgo;
  });

  const queries = recent.filter((r) => r.action === "query");
  const queriesLastHour = queries.length;

  const errStatuses = new Set(["error", "failed", "rate_limited"]);
  const errorsLastHour = recent.filter((r) =>
    r.status && errStatuses.has(r.status),
  ).length;

  const latencies = queries
    .map((r) => r.latency_ms)
    .filter((v): v is number => typeof v === "number" && v > 0)
    .sort((a, b) => a - b);
  const p95LatencyMs = latencies.length
    ? latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * 0.95))]
    : null;

  return { activeTenants, queriesLastHour, errorsLastHour, p95LatencyMs };
}

function NumberCard({
  label,
  value,
  icon: Icon,
  tint,
}: {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  tint?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-4 pb-4 flex items-center justify-between">
        <div>
          <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
            {label}
          </p>
          <p className="text-2xl font-semibold mt-0.5">{value}</p>
        </div>
        <Icon className={`h-6 w-6 ${tint ?? "text-muted-foreground/40"}`} />
      </CardContent>
    </Card>
  );
}
