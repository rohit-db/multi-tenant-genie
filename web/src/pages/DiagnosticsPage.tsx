import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Activity,
  Zap,
  Clock,
  Bot,
  AlertCircle,
  Code2,
  ShieldCheck,
  LayoutGrid,
  CheckCircle2,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { TransportToggle } from "@/components/ask/TransportToggle";
import { Inspector } from "@/components/ask/Inspector";
import { api, type AskResponse, type AskTransport, type Tenant } from "@/lib/api";
import { cn } from "@/lib/utils";

const DEFAULT_QUESTION = "How many bookings do I have and what is my total spend?";

/**
 * Operator-only diagnostics. This is where the proof/dev tooling lives — kept
 * deliberately OUT of the customer product surface:
 *   1. Transport — run a question through the Genie REST API or Managed MCP.
 *   2. Isolation sweep — same question, every tenant, in parallel; the
 *      divergent numbers come from UC row filters, not the model.
 */
export function DiagnosticsPage() {
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const active = useMemo(
    () => (tenants.data ?? []).filter((t) => t.status === "active"),
    [tenants.data],
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
          <Activity className="h-6 w-6 text-[var(--brand)]" />
          Diagnostics
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Proof tooling for operators — transport parity and cross-tenant
          isolation. These controls intentionally live in the console, never on
          the customer product.
        </p>
      </div>

      <TransportPanel
        tenants={active}
        disabled={tenants.isLoading || active.length === 0}
      />
      <SweepPanel tenantCount={active.length} disabled={active.length === 0} />
      <EmbeddingPanel />
    </div>
  );
}

// ============================================================================
// Embedded AI/BI dashboard — config status + grant backfill
// ============================================================================

function EmbeddingPanel() {
  const ws = useQuery({ queryKey: ["ws"], queryFn: api.workspace });
  const backfill = useMutation({ mutationFn: () => api.backfillGrants() });

  const configured = !!ws.data?.embed_configured;
  const dashId = ws.data?.dashboard_id || "";

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <LayoutGrid className="h-4 w-4 text-[var(--brand)]" />
        Embedded AI/BI dashboard
        <span className="text-xs font-normal text-slate-400">
          Native Lakeview dashboard, scoped per tenant SP at embed time
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant="outline"
          className={cn(
            "font-mono text-[11px]",
            configured
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-amber-200 bg-amber-50 text-amber-700",
          )}
        >
          {configured ? (
            <CheckCircle2 className="mr-1 h-3 w-3" />
          ) : (
            <AlertCircle className="mr-1 h-3 w-3" />
          )}
          {configured ? "configured" : "not configured"}
        </Badge>
        {dashId && (
          <Badge variant="secondary" className="font-mono text-[11px]">
            dashboard {dashId.slice(0, 12)}…
          </Badge>
        )}
        <Button
          variant="outline"
          onClick={() => backfill.mutate()}
          disabled={backfill.isPending}
          className="gap-1.5"
        >
          {backfill.isPending ? (
            <Clock className="h-4 w-4 animate-spin" />
          ) : (
            <ShieldCheck className="h-4 w-4" />
          )}
          Backfill grants
        </Button>
      </div>

      <p className="mt-2 text-xs text-slate-500">
        Backfill re-applies SELECT + Genie CAN&nbsp;RUN + dashboard CAN&nbsp;RUN
        to every active tenant SP. Run it after publishing or republishing the
        dashboard.
      </p>

      {backfill.data && (
        <pre className="mt-3 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] font-mono text-slate-700">
          {JSON.stringify(backfill.data, null, 2)}
        </pre>
      )}
      {backfill.isError && (
        <Alert variant="destructive" className="mt-3">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Backfill failed</AlertTitle>
          <AlertDescription>
            {(backfill.error as Error).message}
          </AlertDescription>
        </Alert>
      )}
    </section>
  );
}

// ============================================================================
// Transport — single ask via the chosen transport
// ============================================================================

function TransportPanel({
  tenants,
  disabled,
}: {
  tenants: Tenant[];
  disabled?: boolean;
}) {
  const [tenantId, setTenantId] = useState<string>("");
  const [q, setQ] = useState(DEFAULT_QUESTION);
  const [transport, setTransport] = useState<AskTransport>("mcp");

  useEffect(() => {
    if (!tenantId && tenants.length > 0) setTenantId(tenants[0].tenant_id);
  }, [tenantId, tenants]);

  const run = useMutation({
    mutationFn: () =>
      api.ask(tenantId, q, { inspect: true, transport }),
  });

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <Code2 className="h-4 w-4 text-[var(--brand)]" />
        Genie transport
        <span className="text-xs font-normal text-slate-400">
          REST Conversation API vs Databricks Managed MCP — same answer, same
          isolation
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={tenantId} onValueChange={setTenantId} disabled={disabled}>
          <SelectTrigger className="h-9 w-[180px] text-sm">
            <SelectValue placeholder="Tenant" />
          </SelectTrigger>
          <SelectContent>
            {tenants.map((t) => (
              <SelectItem key={t.tenant_id} value={t.tenant_id}>
                {t.tenant_name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <TransportToggle
          value={transport}
          onChange={setTransport}
          disabled={run.isPending}
        />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="min-w-[240px] flex-1 rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-[var(--brand)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
          placeholder="Question…"
        />
        <Button
          onClick={() => run.mutate()}
          disabled={disabled || !tenantId || !q.trim() || run.isPending}
          className="gap-1.5"
        >
          {run.isPending ? (
            <Clock className="h-4 w-4 animate-spin" />
          ) : (
            <Code2 className="h-4 w-4" />
          )}
          Run
        </Button>
      </div>

      {run.isError && (
        <Alert variant="destructive" className="mt-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Ask failed</AlertTitle>
          <AlertDescription>{(run.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {run.data && !run.isPending && (
        <div className="mt-4 space-y-3 rounded-lg border border-slate-200 bg-slate-50/60 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className="border-emerald-200 bg-emerald-50 font-mono text-[11px] text-emerald-700"
            >
              <ShieldCheck className="mr-1 h-3 w-3" />
              {run.data.status}
            </Badge>
            <Badge variant="secondary" className="font-mono text-[11px]">
              <Clock className="mr-1 h-3 w-3" />
              {run.data.latency_ms} ms
            </Badge>
            <Badge variant="outline" className="font-mono text-[11px]">
              {transport === "mcp" ? "managed mcp" : "rest"}
            </Badge>
          </div>
          {run.data.answer_text && (
            <p className="text-sm leading-relaxed text-slate-800">
              {run.data.answer_text}
            </p>
          )}
          {run.data.sql && (
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-white px-3 py-2 text-[11px] font-mono text-slate-700">
              {run.data.sql}
            </pre>
          )}
          {run.data.inspector && (
            <div className="rounded-md border border-amber-200 bg-white p-3">
              <Inspector payload={run.data.inspector} />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ============================================================================
// Isolation sweep — same question, every tenant, in parallel
// ============================================================================

function SweepPanel({
  tenantCount,
  disabled,
}: {
  tenantCount: number;
  disabled?: boolean;
}) {
  const [q, setQ] = useState(DEFAULT_QUESTION);

  const sweep = useMutation({
    mutationFn: () => api.sweep(q),
  });

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">
        <Zap className="h-4 w-4 text-amber-500" />
        Isolation sweep
        <span className="text-xs font-normal text-slate-400">
          Same question, every tenant — divergence comes from UC row filters,
          not the model
        </span>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="flex-1 rounded-md border border-slate-200 px-3 py-2 text-sm focus:border-[var(--brand)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
          placeholder="Question to run across all tenants…"
        />
        <Button
          onClick={() => sweep.mutate()}
          disabled={disabled || !q.trim() || sweep.isPending}
          className="gap-1.5"
        >
          {sweep.isPending ? (
            <>
              <Clock className="h-4 w-4 animate-spin" />
              Running…
            </>
          ) : (
            <>
              <Zap className="h-4 w-4" />
              Run sweep
            </>
          )}
        </Button>
      </div>

      {sweep.isError && (
        <Alert variant="destructive" className="mt-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Sweep failed</AlertTitle>
          <AlertDescription>{(sweep.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {sweep.isPending && (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: tenantCount || 3 }).map((_, i) => (
            <div
              key={i}
              className="h-32 animate-pulse rounded-lg border border-slate-200 bg-slate-50"
            />
          ))}
        </div>
      )}

      {sweep.data && sweep.data.length > 0 && !sweep.isPending && (
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sweep.data.map((r) => (
            <SweepCard key={r.tenant_id} r={r} />
          ))}
        </div>
      )}
    </section>
  );
}

function SweepCard({ r }: { r: AskResponse }) {
  const first = r.rows[0] ?? [];
  const headline =
    first[0] !== undefined && first[0] !== null ? String(first[0]) : null;
  const failed = r.status === "FAILED";
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm transition-shadow hover:shadow-md">
      <div
        className={cn(
          "h-1 bg-gradient-to-r",
          failed ? "from-rose-300 to-rose-400" : "from-sky-400 to-cyan-400",
        )}
      />
      <div className="space-y-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Bot className="h-4 w-4 text-[var(--brand)]" />
            {r.tenant_name}
          </div>
          <Badge variant="outline" className="font-mono text-[10px]">
            {r.latency_ms} ms
          </Badge>
        </div>
        <div className="truncate font-mono text-[11px] text-slate-400">
          {r.sp_app_id.slice(0, 12)}…
        </div>
        {headline && !failed && (
          <div className="text-2xl font-bold tracking-tight text-[var(--brand-strong)]">
            {formatHeadline(headline)}
          </div>
        )}
        {r.answer_text && (
          <p
            className={cn(
              "line-clamp-3 text-xs leading-snug",
              failed ? "text-rose-600" : "text-slate-500",
            )}
          >
            {r.answer_text}
          </p>
        )}
      </div>
    </div>
  );
}

function formatHeadline(raw: string): string {
  const n = Number(raw);
  if (!Number.isNaN(n) && raw.trim() !== "") {
    if (Number.isInteger(n) && n < 100000) return n.toLocaleString();
    return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  return raw;
}
