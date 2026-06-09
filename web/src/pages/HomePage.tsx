import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Sparkles,
  ArrowRight,
  Gauge,
  Route,
  Building2,
  Plane,
  DollarSign,
  Users,
  TrendingUp,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { BRAND } from "@/brand";
import { AnswerViz } from "@/components/ask/AnswerViz";
import { buildDashboards, type DashboardDef } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const DASH_ICONS = { gauge: Gauge, route: Route, building: Building2 } as const;

const SUGGESTED = [
  "How many bookings do I have and what is my total spend?",
  "Show my top 5 routes by total spend",
  "What's my average booking amount, by cabin class?",
  "Which suppliers appear most in my bookings?",
];

export function HomePage() {
  const { selected, loading } = useTenant();
  const ws = useQuery({ queryKey: ["ws"], queryFn: api.workspace });
  const navigate = useNavigate();

  const fq = ws.data ? `${ws.data.catalog}.${ws.data.schema_name}` : null;
  const tenantId = selected?.tenant_id;

  const metrics = useQuery({
    queryKey: ["home-metrics", tenantId, fq],
    enabled: !!tenantId && !!fq,
    queryFn: () =>
      api.runSql(
        tenantId!,
        `SELECT COUNT(*) AS bookings,
                ROUND(SUM(amount_usd), 0) AS total_spend_usd,
                ROUND(AVG(amount_usd), 0) AS avg_booking_usd,
                COUNT(DISTINCT traveler_name) AS travelers
         FROM ${fq}.bookings`,
      ),
  });

  const trend = useQuery({
    queryKey: ["home-trend", tenantId, fq],
    enabled: !!tenantId && !!fq,
    queryFn: () =>
      api.runSql(
        tenantId!,
        `SELECT DATE_FORMAT(booked_at, 'yyyy-MM') AS month,
                ROUND(SUM(amount_usd), 0) AS spend_usd
         FROM ${fq}.bookings
         GROUP BY DATE_FORMAT(booked_at, 'yyyy-MM')
         ORDER BY month`,
      ),
  });

  const dashboards: DashboardDef[] = useMemo(
    () => (fq ? buildDashboards(fq) : []),
    [fq],
  );

  const ask = (q: string) =>
    navigate(`/ask?q=${encodeURIComponent(q)}`);

  const m = metrics.data;
  const stats = m?.rows?.[0] ?? [];

  return (
    <div className="space-y-10">
      {/* Hero — your own Genie */}
      <section className="animate-fade-up overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div
          className="relative overflow-hidden px-7 py-9 text-white sm:px-10 sm:py-12"
          style={{
            background:
              "linear-gradient(135deg, var(--brand-strong), var(--brand) 60%, #38bdf8)",
          }}
        >
          <div
            aria-hidden
            className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-white/15 blur-3xl"
          />
          <div className="relative flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-medium text-sky-50/90">
              <Sparkles className="h-4 w-4" />
              {selected ? selected.tenant_name : BRAND.name} workspace
            </div>
            <span className="hidden items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/90 backdrop-blur sm:inline-flex">
              <ShieldCheck className="h-3 w-3" />
              Isolated by Unity Catalog
            </span>
          </div>
          <h1 className="relative mt-3 max-w-2xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
            Ask anything about your travel program.
          </h1>
          <p className="relative mt-3 max-w-xl text-sky-50/90">
            {BRAND.name}'s assistant turns plain-English questions into governed
            answers on your own data — no SQL, no spreadsheets.
          </p>

          <div className="relative">
            <HeroAsk onAsk={ask} />
          </div>

          <div className="relative mt-4 flex flex-wrap gap-2">
            {SUGGESTED.slice(0, 3).map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => ask(q)}
                className="rounded-full bg-white/15 px-3 py-1.5 text-xs font-medium text-white backdrop-blur transition-colors hover:bg-white/25"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* KPIs at a glance */}
      <section
        className="grid animate-fade-up grid-cols-2 gap-4 lg:grid-cols-4"
        style={{ animationDelay: "60ms" }}
      >
        <StatCard
          icon={Plane}
          label="Bookings"
          value={fmtInt(stats[0])}
          loading={metrics.isLoading || loading}
        />
        <StatCard
          icon={DollarSign}
          label="Total spend"
          value={fmtUsd(stats[1])}
          loading={metrics.isLoading || loading}
        />
        <StatCard
          icon={TrendingUp}
          label="Avg booking"
          value={fmtUsd(stats[2])}
          loading={metrics.isLoading || loading}
        />
        <StatCard
          icon={Users}
          label="Travelers"
          value={fmtInt(stats[3])}
          loading={metrics.isLoading || loading}
        />
      </section>

      {/* Trend + suggested */}
      <section
        className="grid animate-fade-up grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]"
        style={{ animationDelay: "120ms" }}
      >
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <TrendingUp className="h-4 w-4 text-[var(--brand)]" />
            Spend over time
          </div>
          {trend.data && trend.data.rows.length > 0 ? (
            <AnswerViz columns={trend.data.columns} rows={trend.data.rows} />
          ) : (
            <div className="h-56 animate-pulse rounded-lg bg-slate-100" />
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-800">
            <Sparkles className="h-4 w-4 text-[var(--brand)]" />
            Suggested questions
          </div>
          <div className="space-y-2">
            {SUGGESTED.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => ask(q)}
                className="group flex w-full items-center justify-between gap-3 rounded-lg border border-slate-200 px-3.5 py-2.5 text-left text-sm text-slate-700 transition-all hover:border-[var(--brand)] hover:bg-[var(--brand-soft)]"
              >
                <span className="min-w-0">{q}</span>
                <ArrowRight className="h-4 w-4 shrink-0 text-slate-300 transition-colors group-hover:text-[var(--brand)]" />
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Dashboards */}
      {dashboards.length > 0 && (
        <section
          className="animate-fade-up space-y-4"
          style={{ animationDelay: "180ms" }}
        >
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight text-slate-900">
              Dashboards
            </h2>
            <button
              type="button"
              onClick={() => navigate("/dashboards")}
              className="flex items-center gap-1 text-sm font-medium text-[var(--brand)] hover:underline"
            >
              View all
              <ArrowRight className="h-4 w-4" />
            </button>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {dashboards.map((d) => {
              const Icon = DASH_ICONS[d.icon];
              return (
                <button
                  key={d.id}
                  type="button"
                  onClick={() => navigate(`/dashboards?d=${d.id}`)}
                  className="group flex flex-col gap-2.5 rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition-all hover:-translate-y-0.5 hover:border-[var(--brand)] hover:shadow-md"
                >
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--brand-soft)] text-[var(--brand-strong)]">
                    <Icon className="h-5 w-5" />
                  </span>
                  <div className="text-sm font-semibold text-slate-800">
                    {d.title}
                  </div>
                  <div className="text-xs leading-snug text-slate-500">
                    {d.description}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function HeroAsk({ onAsk }: { onAsk: (q: string) => void }) {
  const [q, setQ] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (q.trim()) onAsk(q.trim());
      }}
      className="mt-6 flex max-w-xl gap-2"
    >
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="e.g. What was my busiest booking month?"
        className="flex-1 rounded-lg border-0 bg-white/95 px-4 py-3 text-sm text-slate-900 shadow-sm outline-none ring-2 ring-transparent placeholder:text-slate-400 focus:ring-white"
      />
      <button
        type="submit"
        className="flex items-center gap-1.5 rounded-lg bg-slate-900/90 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-slate-900"
      >
        Ask
        <ArrowRight className="h-4 w-4" />
      </button>
    </form>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  loading,
}: {
  icon: typeof Plane;
  label: string;
  value: string;
  loading?: boolean;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-400">
        <Icon className="h-4 w-4 text-[var(--brand)]" />
        {label}
      </div>
      <div
        className={cn(
          "mt-2 text-2xl font-semibold tracking-tight text-slate-900",
          loading && "animate-pulse text-slate-300",
        )}
      >
        {loading ? "—" : value}
      </div>
    </div>
  );
}

function fmtInt(v: unknown): string {
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString() : "—";
}

function fmtUsd(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}
