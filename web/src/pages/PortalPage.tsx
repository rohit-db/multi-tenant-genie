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
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  CartesianGrid,
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
} from "lucide-react";
import { api, type AskResponse, type Tenant } from "@/lib/api";

// Pre-canned questions that drive the dashboard widgets.
const Q_KPIS =
  "How many bookings do I have, what is my total spend, what is my average booking amount, and how many distinct travelers do I have? Return one row.";
const Q_TOP_ROUTES = "Show my top 5 routes by total spend";
const Q_CABIN_MIX = "Show count of bookings by cabin class";

const CHART_COLORS = [
  "#6366f1", // indigo
  "#22c55e", // emerald
  "#f59e0b", // amber
  "#ef4444", // rose
  "#06b6d4", // cyan
  "#8b5cf6", // violet
];

interface ChatTurn {
  question: string;
  answer: AskResponse | null;
  pending: boolean;
  error?: string;
}

export function PortalPage() {
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const active = useMemo(
    () => (tenants.data ?? []).filter((t) => t.status === "active"),
    [tenants.data],
  );
  const [tenantId, setTenantId] = useState<string | undefined>(undefined);

  // Pick first active tenant by default
  useEffect(() => {
    if (!tenantId && active.length > 0) {
      setTenantId(active[0].tenant_id);
    }
  }, [tenantId, active]);

  const tenant = active.find((t) => t.tenant_id === tenantId);

  return (
    <div className="space-y-6">
      <ProblemStatement />

      {tenants.isLoading ? (
        <div className="text-sm text-muted-foreground">Loading tenants…</div>
      ) : active.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No active tenants yet. Onboard one in the Admin tab to populate
            this dashboard.
          </CardContent>
        </Card>
      ) : tenant ? (
        <Dashboard tenant={tenant} active={active} setTenantId={setTenantId} />
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
}: {
  tenant: Tenant;
  active: Tenant[];
  setTenantId: (id: string) => void;
}) {
  const kpis = useGenieQuery(tenant.tenant_id, Q_KPIS);
  const routes = useGenieQuery(tenant.tenant_id, Q_TOP_ROUTES);
  const cabin = useGenieQuery(tenant.tenant_id, Q_CABIN_MIX);

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
          <Select
            value={tenant.tenant_id}
            onValueChange={(v) => setTenantId(v)}
          >
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

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_380px] gap-5">
        <div className="space-y-5 min-w-0">
          <KpiRow kpis={kpis} />
          <RoutesCard data={routes} />
          <CabinMixCard data={cabin} />
        </div>
        <div className="lg:sticky lg:top-20 lg:self-start min-w-0">
          <ChatPanel tenant={tenant} />
        </div>
      </div>
    </>
  );
}

function KpiRow({ kpis }: { kpis: ReturnType<typeof useGenieQuery> }) {
  const stats = parseKpiRow(kpis.data);
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <KpiCard
        label="Bookings"
        value={stats.bookings}
        icon={Plane}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Total spend"
        value={stats.totalSpend}
        icon={DollarSign}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Avg booking"
        value={stats.avgBooking}
        icon={DollarSign}
        loading={kpis.isLoading}
      />
      <KpiCard
        label="Travelers"
        value={stats.travelers}
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

function RoutesCard({ data }: { data: ReturnType<typeof useGenieQuery> }) {
  const rows = parseLabelValue(data.data);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top routes by spend</CardTitle>
        <CardDescription>
          Genie generated SQL; rows here are this tenant&rsquo;s only.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.isLoading ? (
          <div className="h-[220px] bg-slate-50 rounded animate-pulse" />
        ) : rows.length === 0 ? (
          <EmptyChart message="No data" />
        ) : (
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
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
                />
                <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CabinMixCard({ data }: { data: ReturnType<typeof useGenieQuery> }) {
  const rows = parseLabelValue(data.data);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Cabin class mix</CardTitle>
        <CardDescription>
          Distribution of this tenant&rsquo;s bookings.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.isLoading ? (
          <div className="h-[220px] bg-slate-50 rounded animate-pulse" />
        ) : rows.length === 0 ? (
          <EmptyChart message="No data" />
        ) : (
          <div className="h-[220px]">
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
                    <Cell
                      key={i}
                      fill={CHART_COLORS[i % CHART_COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    fontSize: 12,
                    border: "1px solid #e2e8f0",
                    borderRadius: 6,
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="h-[220px] flex items-center justify-center text-xs text-slate-500">
      {message}
    </div>
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

  // Reset chat on tenant switch
  useEffect(() => {
    setHistory([]);
    setDraft("");
  }, [tenant.tenant_id]);

  // Scroll to bottom on new turn
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history]);

  const submit = () => {
    const q = draft.trim();
    if (!q || ask.isPending) return;
    setHistory((h) => [...h, { question: q, answer: null, pending: true }]);
    setDraft("");
    ask.mutate(q);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base flex items-center gap-2">
          <Bot className="h-4 w-4 text-indigo-600" />
          Ask the data
        </CardTitle>
        <CardDescription>
          Powered by Genie, scoped to {tenant.tenant_name}&rsquo;s rows. Ask
          anything about your bookings, routes, or travelers.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          ref={scrollRef}
          className="rounded-md border bg-slate-50/40 p-3 max-h-[260px] overflow-y-auto space-y-3"
        >
          {history.length === 0 ? (
            <EmptyChat />
          ) : (
            history.map((turn, i) => <ChatTurnRow key={i} turn={turn} />)
          )}
        </div>

        <div className="flex gap-2">
          <Input
            placeholder={`Ask anything about ${tenant.tenant_name}'s data…`}
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
          <Button onClick={submit} disabled={!draft.trim() || ask.isPending}>
            {ask.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>

        <SuggestionChips
          onPick={(q) => {
            setDraft(q);
          }}
        />
      </CardContent>
    </Card>
  );
}

function EmptyChat() {
  return (
    <div className="text-xs text-slate-500 text-center py-6">
      Ask a question to start. The proxy mints a token as this tenant&rsquo;s
      Service Principal; UC row filters scope every result automatically.
    </div>
  );
}

function ChatTurnRow({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <div className="h-6 w-6 rounded-full bg-slate-200 flex items-center justify-center shrink-0 mt-0.5">
          <User className="h-3 w-3 text-slate-600" />
        </div>
        <div className="text-sm pt-0.5">{turn.question}</div>
      </div>
      <div className="flex items-start gap-2">
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

function ChatAnswer({ a }: { a: AskResponse }) {
  return (
    <div className="space-y-1.5">
      {a.answer_text && <div className="text-slate-800">{a.answer_text}</div>}
      {a.rows.length > 0 && (
        <div className="rounded border bg-white text-xs overflow-x-auto">
          <table className="min-w-full">
            <thead className="bg-slate-50 border-b">
              <tr>
                {a.columns.map((c) => (
                  <th
                    key={c}
                    className="text-left font-medium text-slate-600 px-2 py-1.5"
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
                    <td key={j} className="px-2 py-1.5 font-mono">
                      {formatCell(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-[10px] text-slate-400 font-mono">
        {a.latency_ms} ms · {a.rows.length} row{a.rows.length === 1 ? "" : "s"}
      </div>
    </div>
  );
}

function SuggestionChips({ onPick }: { onPick: (q: string) => void }) {
  const chips = [
    "What was my busiest month?",
    "Which suppliers do I use most?",
    "Top travelers by spend",
  ];
  return (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onPick(c)}
          className="text-[11px] text-slate-600 hover:text-slate-900 border border-slate-200 hover:border-slate-300 rounded-full px-2.5 py-1 bg-white"
        >
          {c}
        </button>
      ))}
    </div>
  );
}

// ============================================================================
// helpers
// ============================================================================

function useGenieQuery(tenantId: string, question: string) {
  return useQuery({
    queryKey: ["genie-portal", tenantId, question],
    queryFn: () => api.ask(tenantId, question),
    staleTime: 60_000,
    retry: false,
  });
}

function parseKpiRow(resp: AskResponse | undefined) {
  const empty = {
    bookings: "—",
    totalSpend: "—",
    avgBooking: "—",
    travelers: "—",
  };
  if (!resp || resp.rows.length === 0) return empty;
  const row = resp.rows[0];
  // Try to find columns by name first; fall back to positional.
  const idx = (...names: string[]): number => {
    for (const n of names) {
      const i = resp.columns.findIndex((c) =>
        c.toLowerCase().includes(n.toLowerCase()),
      );
      if (i >= 0) return i;
    }
    return -1;
  };
  const bookingsIdx = idx("bookings", "count");
  const spendIdx = idx("total_spend", "spend", "sum");
  const avgIdx = idx("avg", "average", "mean");
  const travelersIdx = idx("travelers", "distinct");

  const get = (i: number, fallback: number): unknown =>
    i >= 0 && i < row.length ? row[i] : row[fallback] ?? null;

  return {
    bookings: formatNumber(get(bookingsIdx, 0)),
    totalSpend: formatMoney(get(spendIdx, 1)),
    avgBooking: formatMoney(get(avgIdx, 2)),
    travelers: formatNumber(get(travelersIdx, 3)),
  };
}

function parseLabelValue(
  resp: AskResponse | undefined,
): Array<{ label: string; value: number }> {
  if (!resp || resp.rows.length === 0) return [];
  return resp.rows.slice(0, 8).map((r) => ({
    label: String(r[0] ?? ""),
    value: Number(r[1] ?? 0),
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
