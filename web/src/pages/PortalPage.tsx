import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
  Legend,
} from "recharts";
import {
  Plane,
  DollarSign,
  Users,
  Send,
  Loader2,
  Bot,
  User,
  Lock,
  RotateCcw,
  Database,
  Wand2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { api, type Tenant, type WorkspaceInfo } from "@/lib/api";

const CHART_COLORS = [
  "#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#8b5cf6",
];

type SqlResult = {
  columns: string[];
  rows: (string | number | null)[][];
  latency_ms: number;
};

interface ChatTurn {
  question: string;
  answer: import("@/lib/api").AskResponse | null;
  pending: boolean;
  error?: string;
}

export function PortalPage() {
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const ws = useQuery({ queryKey: ["ws"], queryFn: api.workspace });
  const active = useMemo(
    () => (tenants.data ?? []).filter((t) => t.status === "active"),
    [tenants.data],
  );
  const [tenantId, setTenantId] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!tenantId && active.length > 0) {
      // Prefer the canonical seeded demo tenants (which have bookings data)
      // when present; fall back to the first active tenant otherwise.
      const PREFERRED = ["acme", "nike", "cloudventure"];
      const preferred = PREFERRED
        .map((p) => active.find((t) => t.tenant_id === p))
        .find((t) => t !== undefined);
      setTenantId(preferred?.tenant_id ?? active[0].tenant_id);
    }
  }, [tenantId, active]);

  const tenant = active.find((t) => t.tenant_id === tenantId);

  return (
    <div className="space-y-6">
      <ProblemStatement />

      {tenants.isLoading || ws.isLoading ? (
        <div className="text-sm text-muted-foreground">Loading…</div>
      ) : active.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No active tenants yet. Onboard one in the Admin tab to populate
            this dashboard.
          </CardContent>
        </Card>
      ) : tenant && ws.data ? (
        <Dashboard
          tenant={tenant}
          active={active}
          setTenantId={setTenantId}
          ws={ws.data}
        />
      ) : null}
    </div>
  );
}

function ProblemStatement() {
  return (
    <p className="text-sm text-slate-600 max-w-3xl">
      A typical SaaS data app: branded portal, tenant-scoped charts, embedded
      Genie chat. The hard part isn&rsquo;t the dashboard — it&rsquo;s
      guaranteeing <span className="font-medium text-slate-900">tenant A
      never sees tenant B&rsquo;s data</span> when they share the same
      workspace, warehouse, and Genie Space. Below is one tenant&rsquo;s view,
      served through this reference proxy.
    </p>
  );
}

function Dashboard({
  tenant,
  active,
  setTenantId,
  ws,
}: {
  tenant: Tenant;
  active: Tenant[];
  setTenantId: (id: string) => void;
  ws: WorkspaceInfo;
}) {
  const fq = `${ws.catalog}.${ws.schema_name}`;

  const sqlKpis = `SELECT
    COUNT(*) AS bookings,
    SUM(amount_usd) AS total_spend,
    AVG(amount_usd) AS avg_booking,
    COUNT(DISTINCT traveler_name) AS travelers
  FROM ${fq}.bookings`;

  const sqlTopRoutes = `SELECT route, ROUND(SUM(amount_usd), 0) AS spend
  FROM ${fq}.bookings
  GROUP BY route
  ORDER BY spend DESC
  LIMIT 5`;

  const sqlCabinMix = `SELECT cabin_class, COUNT(*) AS bookings
  FROM ${fq}.bookings
  GROUP BY cabin_class
  ORDER BY bookings DESC`;

  const sqlMonthlyTrend = `SELECT
    DATE_FORMAT(booked_at, 'yyyy-MM') AS month,
    COUNT(*) AS bookings,
    ROUND(SUM(amount_usd), 0) AS spend
  FROM ${fq}.bookings
  GROUP BY DATE_FORMAT(booked_at, 'yyyy-MM')
  ORDER BY month`;

  const sqlTopSuppliers = `SELECT supplier, COUNT(*) AS bookings,
    ROUND(SUM(amount_usd), 0) AS spend
  FROM ${fq}.bookings
  GROUP BY supplier
  ORDER BY bookings DESC
  LIMIT 6`;

  const kpis = useSqlQuery(tenant.tenant_id, sqlKpis);
  const routes = useSqlQuery(tenant.tenant_id, sqlTopRoutes);
  const cabin = useSqlQuery(tenant.tenant_id, sqlCabinMix);
  const trend = useSqlQuery(tenant.tenant_id, sqlMonthlyTrend);
  const suppliers = useSqlQuery(tenant.tenant_id, sqlTopSuppliers);

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Plane className="h-4 w-4 text-indigo-600 shrink-0" />
          <span className="text-sm font-medium">
            {tenant.tenant_name}&rsquo;s travel desk
          </span>
          <Badge
            variant="outline"
            className="font-mono text-[10px] gap-1 border-emerald-200 text-emerald-700 bg-emerald-50"
          >
            <Lock className="h-2.5 w-2.5" />
            row-filtered
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider text-slate-500">
            Acting as
          </span>
          <Select value={tenant.tenant_id} onValueChange={(v) => setTenantId(v)}>
            <SelectTrigger className="h-8 w-[200px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {active.map((t) => (
                <SelectItem key={t.tenant_id} value={t.tenant_id}>
                  {t.tenant_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_400px] gap-5">
        <div className="space-y-5 min-w-0">
          <KpiRow kpis={kpis} />
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            <RoutesCard data={routes} />
            <CabinMixCard data={cabin} />
          </div>
          <MonthlyTrendCard data={trend} />
          <SuppliersCard data={suppliers} />
          <InsightsAgentCard tenant={tenant} />
        </div>
        <div className="lg:sticky lg:top-20 lg:self-start min-w-0">
          <ChatPanel tenant={tenant} />
        </div>
      </div>
    </>
  );
}

function KpiRow({ kpis }: { kpis: ReturnType<typeof useSqlQuery> }) {
  const row = kpis.data?.rows[0] ?? [];
  const cols = kpis.data?.columns ?? [];
  const get = (n: string) => {
    const i = cols.findIndex((c) => c.toLowerCase() === n);
    return i >= 0 ? row[i] : null;
  };
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <KpiCard
        label="Bookings"
        value={formatNumber(get("bookings"))}
        icon={Plane}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Total spend"
        value={formatMoney(get("total_spend"))}
        icon={DollarSign}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Avg booking"
        value={formatMoney(get("avg_booking"))}
        icon={DollarSign}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Travelers"
        value={formatNumber(get("travelers"))}
        icon={Users}
        loading={kpis.isLoading}
      />
    </div>
  );
}

function KpiCard({
  label,
  value,
  icon: Icon,
  loading,
}: {
  label: string;
  value: string;
  icon: React.ComponentType<{ className?: string }>;
  loading: boolean;
}) {
  return (
    <Card>
      <CardContent className="pt-4 pb-4 flex items-center justify-between">
        <div className="min-w-0">
          <p className="text-[11px] uppercase tracking-wider text-slate-500">
            {label}
          </p>
          {loading ? (
            <div className="h-7 w-20 bg-slate-100 rounded animate-pulse mt-1" />
          ) : (
            <p className="text-2xl font-semibold mt-0.5 tabular-nums truncate">
              {value}
            </p>
          )}
        </div>
        <Icon className="h-5 w-5 text-slate-300 shrink-0" />
      </CardContent>
    </Card>
  );
}

function RoutesCard({ data }: { data: ReturnType<typeof useSqlQuery> }) {
  const rows = parseLabelValue(data.data, "route", "spend");
  return (
    <ChartShell
      title="Top routes by spend"
      description="Total USD billed per route, this tenant only."
      loading={data.isLoading}
      empty={rows.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          margin={{ top: 8, right: 8, left: -16, bottom: 0 }}
        >
          <CartesianGrid stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              border: "1px solid #e2e8f0",
              borderRadius: 6,
            }}
            formatter={(v) => [formatMoney(v), "Spend"]}
          />
          <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

function CabinMixCard({ data }: { data: ReturnType<typeof useSqlQuery> }) {
  const rows = parseLabelValue(data.data, "cabin_class", "bookings");
  return (
    <ChartShell
      title="Cabin class mix"
      description="Distribution of this tenant's bookings."
      loading={data.isLoading}
      empty={rows.length === 0}
    >
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={rows}
            dataKey="value"
            nameKey="label"
            cx="50%"
            cy="50%"
            innerRadius={50}
            outerRadius={80}
            paddingAngle={2}
          >
            {rows.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Legend
            verticalAlign="bottom"
            height={28}
            iconSize={8}
            wrapperStyle={{ fontSize: 11, color: "#64748b" }}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              border: "1px solid #e2e8f0",
              borderRadius: 6,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

function MonthlyTrendCard({ data }: { data: ReturnType<typeof useSqlQuery> }) {
  const rows = useMemo(() => {
    if (!data.data) return [];
    return data.data.rows.map((r) => ({
      month: String(r[0] ?? ""),
      bookings: Number(r[1] ?? 0),
      spend: Number(r[2] ?? 0),
    }));
  }, [data.data]);

  return (
    <ChartShell
      title="Bookings + spend over time"
      description="Monthly trend, this tenant only."
      loading={data.isLoading}
      empty={rows.length === 0}
      height={240}
    >
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={rows}
          margin={{ top: 12, right: 12, left: -16, bottom: 0 }}
        >
          <CartesianGrid stroke="#f1f5f9" vertical={false} />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={{ stroke: "#e2e8f0" }}
            tickLine={false}
          />
          <YAxis
            yAxisId="left"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            yAxisId="right"
            orientation="right"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              border: "1px solid #e2e8f0",
              borderRadius: 6,
            }}
          />
          <Legend
            verticalAlign="top"
            iconSize={8}
            wrapperStyle={{ fontSize: 11, color: "#64748b" }}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="bookings"
            stroke="#6366f1"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="spend"
            stroke="#22c55e"
            strokeWidth={2}
            dot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

function SuppliersCard({ data }: { data: ReturnType<typeof useSqlQuery> }) {
  const rows = useMemo(() => {
    if (!data.data) return [];
    return data.data.rows.map((r) => ({
      supplier: String(r[0] ?? ""),
      bookings: Number(r[1] ?? 0),
      spend: Number(r[2] ?? 0),
    }));
  }, [data.data]);

  return (
    <ChartShell
      title="Top suppliers"
      description="By booking count + total spend."
      loading={data.isLoading}
      empty={rows.length === 0}
      height={240}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={rows}
          layout="vertical"
          margin={{ top: 8, right: 16, left: 60, bottom: 0 }}
        >
          <CartesianGrid stroke="#f1f5f9" horizontal={false} />
          <XAxis
            type="number"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="supplier"
            tick={{ fontSize: 11, fill: "#475569" }}
            axisLine={false}
            tickLine={false}
            width={80}
          />
          <Tooltip
            contentStyle={{
              fontSize: 12,
              border: "1px solid #e2e8f0",
              borderRadius: 6,
            }}
          />
          <Bar dataKey="bookings" fill="#06b6d4" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartShell>
  );
}

function ChartShell({
  title,
  description,
  loading,
  empty,
  height = 220,
  children,
}: {
  title: string;
  description: string;
  loading: boolean;
  empty: boolean;
  height?: number;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {loading ? (
          <div
            className="bg-slate-50 rounded animate-pulse"
            style={{ height }}
          />
        ) : empty ? (
          <div
            className="flex items-center justify-center text-xs text-slate-500"
            style={{ height }}
          >
            No data
          </div>
        ) : (
          <div style={{ height }}>{children}</div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// Insights agent
// ============================================================================

const SUGGESTED_FOCUS = [
  "Where am I spending the most and what's growing fastest?",
  "Anomalies in my booking patterns this quarter",
  "Which suppliers should I renegotiate with?",
];

function InsightsAgentCard({ tenant }: { tenant: Tenant }) {
  const [focus, setFocus] = useState(SUGGESTED_FOCUS[0]);

  const insights = useMutation({
    mutationFn: () => api.agentInsights(tenant.tenant_id, focus),
  });

  // Reset on tenant change
  useEffect(() => {
    insights.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenant.tenant_id]);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Wand2 className="h-4 w-4 text-violet-600" />
          Insights agent
        </CardTitle>
        <CardDescription>
          Custom agent: LLM picks SQL queries, runs them as{" "}
          <span className="font-medium">{tenant.tenant_name}</span> (row filter
          applies), and synthesizes a recommendation. Same isolation pattern
          Genie uses — applied to any agent.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label className="text-[11px] uppercase tracking-wider text-slate-500">
            Focus area
          </label>
          <Input
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            disabled={insights.isPending}
          />
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED_FOCUS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setFocus(s)}
                className="text-[11px] text-slate-600 hover:text-slate-900 border border-slate-200 hover:border-slate-300 rounded-full px-2.5 py-1 bg-white"
                disabled={insights.isPending}
              >
                {s}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3">
          <Button
            onClick={() => insights.mutate()}
            disabled={!focus.trim() || insights.isPending}
            className="bg-violet-600 hover:bg-violet-700 text-white"
          >
            {insights.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Running…
              </>
            ) : (
              <>
                <Wand2 className="h-4 w-4 mr-2" />
                Run insights
              </>
            )}
          </Button>
          {insights.data && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => insights.reset()}
              className="text-[11px]"
            >
              Clear
            </Button>
          )}
        </div>

        {insights.isError && (
          <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded px-3 py-2">
            {(insights.error as Error).message}
          </div>
        )}

        {insights.data && <InsightsOutput data={insights.data} />}
      </CardContent>
    </Card>
  );
}

function InsightsOutput({
  data,
}: {
  data: NonNullable<ReturnType<typeof api.agentInsights> extends Promise<infer R> ? R : never>;
}) {
  return (
    <div className="space-y-4 pt-2 border-t">
      {data.reasoning && (
        <div>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
            Plan
          </div>
          <p className="text-sm text-slate-700 italic">"{data.reasoning}"</p>
        </div>
      )}

      <div className="space-y-2">
        <div className="text-[10px] uppercase tracking-wider text-slate-500">
          Tool calls ({data.tool_calls.length})
        </div>
        <div className="space-y-2">
          {data.tool_calls.map((tc, i) => (
            <ToolCallRow key={i} tc={tc} />
          ))}
        </div>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">
          Recommendation
        </div>
        <div className="rounded-md border border-violet-200 bg-violet-50/60 px-3 py-2.5 text-sm leading-relaxed text-slate-800">
          {data.recommendation}
        </div>
      </div>

      <div className="text-[10px] font-mono text-slate-400">
        model: {data.model} · same SP-per-tenant + row filter pattern
      </div>
    </div>
  );
}

function ToolCallRow({
  tc,
}: {
  tc: {
    name: string;
    sql: string;
    columns?: string[];
    rows?: (string | number | null)[][];
    row_count?: number;
    latency_ms?: number;
    error?: string;
  };
}) {
  return (
    <details className="rounded-md border bg-white">
      <summary className="cursor-pointer px-3 py-2 text-xs flex items-center gap-2 select-none hover:bg-slate-50">
        {tc.error ? (
          <AlertCircle className="h-3.5 w-3.5 text-rose-600 shrink-0" />
        ) : (
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
        )}
        <span className="font-medium">{tc.name}</span>
        <span className="ml-auto text-[10px] font-mono text-slate-500">
          {tc.error
            ? "error"
            : `${tc.row_count ?? 0} rows · ${tc.latency_ms ?? 0} ms`}
        </span>
      </summary>
      <div className="px-3 pb-3 space-y-2">
        <pre className="text-[11px] bg-slate-50 border rounded px-2 py-1.5 overflow-x-auto whitespace-pre-wrap font-mono text-slate-700">
          {tc.sql}
        </pre>
        {tc.error ? (
          <div className="text-[11px] text-rose-700 font-mono">{tc.error}</div>
        ) : tc.rows && tc.rows.length > 0 ? (
          <div className="rounded border bg-white text-[11px] overflow-x-auto">
            <table className="min-w-full">
              <thead className="bg-slate-50 border-b">
                <tr>
                  {(tc.columns ?? []).map((c) => (
                    <th
                      key={c}
                      className="text-left font-medium text-slate-600 px-2 py-1 whitespace-nowrap"
                    >
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tc.rows.slice(0, 5).map((r, i) => (
                  <tr key={i} className="border-b last:border-0">
                    {r.map((v, j) => (
                      <td
                        key={j}
                        className="px-2 py-1 font-mono whitespace-nowrap"
                      >
                        {formatCell(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>
    </details>
  );
}

function ChatPanel({ tenant }: { tenant: Tenant }) {
  const [history, setHistory] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const ask = useMutation({
    mutationFn: (q: string) => api.ask(tenant.tenant_id, q),
    onSuccess: (resp, q) => {
      setHistory((h) =>
        h.map((turn, i) =>
          i === h.length - 1 && turn.question === q && turn.pending
            ? { ...turn, answer: resp, pending: false }
            : turn,
        ),
      );
    },
    onError: (err: Error, q) => {
      setHistory((h) =>
        h.map((turn, i) =>
          i === h.length - 1 && turn.question === q && turn.pending
            ? { ...turn, pending: false, error: err.message }
            : turn,
        ),
      );
    },
  });

  useEffect(() => {
    setHistory([]);
    setDraft("");
  }, [tenant.tenant_id]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  const submit = (q?: string) => {
    const text = (q ?? draft).trim();
    if (!text || ask.isPending) return;
    setHistory((h) => [...h, { question: text, answer: null, pending: true }]);
    setDraft("");
    ask.mutate(text);
  };

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <CardTitle className="text-base flex items-center gap-2">
              <Bot className="h-4 w-4 text-indigo-600" />
              Ask the data
            </CardTitle>
            <CardDescription className="mt-1">
              Genie, scoped to {tenant.tenant_name}&rsquo;s rows.
            </CardDescription>
          </div>
          {history.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-[11px] text-slate-500 hover:text-slate-900"
              onClick={() => setHistory([])}
            >
              <RotateCcw className="h-3 w-3 mr-1" />
              Clear
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          ref={scrollRef}
          className="rounded-md border bg-slate-50/40 p-3.5 h-[360px] overflow-y-auto space-y-4"
        >
          {history.length === 0 ? (
            <EmptyChat tenantName={tenant.tenant_name} onPick={(q) => submit(q)} />
          ) : (
            history.map((turn, i) => <ChatTurnRow key={i} turn={turn} />)
          )}
        </div>

        <div className="flex gap-2">
          <Input
            placeholder={`Ask about ${tenant.tenant_name}'s data…`}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={ask.isPending}
          />
          <Button onClick={() => submit()} disabled={!draft.trim() || ask.isPending}>
            {ask.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

const STARTER_QUESTIONS = [
  "What was my busiest month?",
  "Which suppliers do I use most?",
  "Top 5 travelers by spend",
  "How many international trips this year?",
];

function EmptyChat({
  tenantName,
  onPick,
}: {
  tenantName: string;
  onPick: (q: string) => void;
}) {
  return (
    <div className="space-y-3 py-2">
      <p className="text-xs text-slate-500 leading-relaxed">
        Ask any question about <span className="font-medium">{tenantName}</span>
        &rsquo;s data. The proxy mints a Service Principal token and Genie
        runs the query — UC row filters scope every result.
      </p>
      <div className="space-y-1.5">
        {STARTER_QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="w-full text-left text-xs text-slate-700 hover:text-slate-900 hover:bg-white border border-slate-200 rounded-md px-2.5 py-2 bg-white/60 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function ChatTurnRow({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-start gap-2.5">
        <div className="h-6 w-6 rounded-full bg-slate-200 flex items-center justify-center shrink-0 mt-0.5">
          <User className="h-3 w-3 text-slate-600" />
        </div>
        <div className="text-sm pt-0.5 flex-1 min-w-0">{turn.question}</div>
      </div>
      <div className="flex items-start gap-2.5">
        <div className="h-6 w-6 rounded-full bg-indigo-100 flex items-center justify-center shrink-0 mt-0.5">
          <Bot className="h-3 w-3 text-indigo-700" />
        </div>
        <div className="text-sm pt-0.5 flex-1 min-w-0">
          {turn.pending ? (
            <span className="text-slate-500 inline-flex items-center gap-1.5">
              <Loader2 className="h-3 w-3 animate-spin" />
              Thinking…
            </span>
          ) : turn.error ? (
            <span className="text-rose-700 text-xs">{turn.error}</span>
          ) : turn.answer ? (
            <ChatAnswer a={turn.answer} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ChatAnswer({ a }: { a: import("@/lib/api").AskResponse }) {
  return (
    <div className="space-y-2">
      {a.answer_text && (
        <div className="text-slate-800 leading-relaxed">{a.answer_text}</div>
      )}
      {a.rows.length > 0 && (
        <div className="rounded border bg-white text-xs overflow-x-auto">
          <table className="min-w-full">
            <thead className="bg-slate-50 border-b">
              <tr>
                {a.columns.map((c) => (
                  <th
                    key={c}
                    className="text-left font-medium text-slate-600 px-2 py-1.5 whitespace-nowrap"
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {a.rows.slice(0, 8).map((r, i) => (
                <tr key={i} className="border-b last:border-0">
                  {r.map((v, j) => (
                    <td key={j} className="px-2 py-1.5 font-mono whitespace-nowrap">
                      {formatCell(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-[10px] text-slate-400 font-mono flex items-center gap-2">
        <span className="inline-flex items-center gap-1">
          <Database className="h-2.5 w-2.5" />
          via Genie
        </span>
        <span>·</span>
        <span>{a.latency_ms} ms</span>
        <span>·</span>
        <span>{a.rows.length} row{a.rows.length === 1 ? "" : "s"}</span>
      </div>
    </div>
  );
}

// ============================================================================
// helpers
// ============================================================================

function useSqlQuery(tenantId: string, sql: string) {
  return useQuery<SqlResult>({
    queryKey: ["portal-sql", tenantId, sql],
    queryFn: () => api.runSql(tenantId, sql),
    staleTime: 60_000,
    retry: false,
  });
}

function parseLabelValue(
  resp: SqlResult | undefined,
  labelCol: string,
  valueCol: string,
): Array<{ label: string; value: number }> {
  if (!resp) return [];
  const li = resp.columns.findIndex((c) => c.toLowerCase() === labelCol);
  const vi = resp.columns.findIndex((c) => c.toLowerCase() === valueCol);
  return resp.rows.slice(0, 8).map((r) => ({
    label: String(r[li >= 0 ? li : 0] ?? ""),
    value: Number(r[vi >= 0 ? vi : 1] ?? 0),
  }));
}

function formatNumber(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function formatMoney(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(0)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatCell(v: string | number | null): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return v.toLocaleString();
  const n = Number(v);
  if (Number.isFinite(n) && String(v).match(/^-?\d/)) {
    if (Number.isInteger(n)) return n.toLocaleString();
    return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(v);
}
