import { useMemo, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Sparkles,
  Lock,
  ShieldCheck,
  Zap,
  AlertCircle,
  Bot,
  Code2,
  Columns,
  Clock,
  Plane,
  Info,
  Lightbulb,
} from "lucide-react";
import { api, type AskResponse, type Tenant } from "@/lib/api";

const DEFAULT_Q =
  "How many bookings do I have and what is my total spend?";

const SAMPLE_QUESTIONS = [
  "How many bookings do I have and what is my total spend?",
  "Show my top 5 routes by total spend",
  "What's my average booking amount, by cabin class?",
  "Which suppliers appear most in my bookings?",
  "Which cabin class do my travelers use most?",
];

export function ClientPage() {
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const active = useMemo(
    () =>
      (tenants.data ?? []).filter(
        (t) => t.status === "active" && t.has_local_secret,
      ),
    [tenants.data],
  );
  const [pick, setPick] = useState<string | undefined>(undefined);
  const [q, setQ] = useState(DEFAULT_Q);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [sweep, setSweep] = useState<AskResponse[] | null>(null);

  const ask = useMutation({
    mutationFn: () => api.ask(pick!, q),
    onSuccess: (r) => setAnswer(r),
  });
  const sweepM = useMutation({
    mutationFn: () => api.sweep(q),
    onSuccess: (r) => setSweep(r),
  });

  const selected: Tenant | undefined = active.find((t) => t.tenant_id === pick);

  // auto-pick first tenant
  if (!pick && active.length > 0) {
    setTimeout(() => setPick(active[0].tenant_id), 0);
  }

  const busy = ask.isPending || sweepM.isPending;

  return (
    <div className="space-y-6">
      {/* Use-case framing */}
      <Card className="border-indigo-100 bg-gradient-to-br from-indigo-50/50 to-white">
        <CardContent className="py-5">
          <div className="flex items-start gap-3">
            <div className="h-9 w-9 rounded-lg bg-indigo-100 flex items-center justify-center shrink-0">
              <Info className="h-4 w-4 text-indigo-600" />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium leading-tight">
                Embedded analytics — multi-tenant isolation pattern
              </p>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Each tenant queries through its own Service Principal; UC row
                filters keep query results scoped to that tenant's data.
                The proxy mints per-tenant OAuth tokens and audits every
                request. Every tenant sees only{" "}
                <span className="font-mono">client_credentials</span>{" "}
                per-tenant and lets Unity Catalog row filters — not Genie
                prompts — do the enforcement. Pick a tenant below and watch
                the same question return tenant-scoped data.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="border-indigo-100 shadow-sm">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-indigo-600" />
            Ask Genie as a tenant
          </CardTitle>
          <CardDescription>
            Each query mints a fresh OAuth token via{" "}
            <code className="text-[11px] bg-slate-100 px-1 rounded">
              client_credentials
            </code>{" "}
            as the tenant's Service Principal. UC row filters enforce isolation
            transparently — Genie generates one SQL query over the shared
            table; only the tenant's rows come back.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {tenants.isLoading ? (
            <div className="space-y-3">
              <div className="h-10 rounded-md bg-slate-100 animate-pulse" />
              <div className="h-20 rounded-md bg-slate-100 animate-pulse" />
            </div>
          ) : active.length === 0 ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>No active tenants with stored secrets</AlertTitle>
              <AlertDescription>
                Onboard a tenant on the Admin tab first (or rotate one to
                regenerate a local secret).
              </AlertDescription>
            </Alert>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-5">
              <div className="space-y-3">
                <label className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                  I am…
                </label>
                <Select value={pick} onValueChange={setPick}>
                  <SelectTrigger>
                    <SelectValue placeholder="Pick a tenant" />
                  </SelectTrigger>
                  <SelectContent>
                    {active.map((t) => (
                      <SelectItem key={t.tenant_id} value={t.tenant_id}>
                        {t.tenant_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {selected && (
                  <div className="rounded-lg border bg-gradient-to-br from-slate-50 to-white p-3 space-y-2 shadow-sm">
                    <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-indigo-700">
                      <Lock className="h-3 w-3" />
                      Active identity
                    </div>
                    <div className="text-xs font-mono space-y-1">
                      <div>
                        <span className="text-muted-foreground">tenant</span>{" "}
                        <span className="text-slate-900">
                          {selected.tenant_id}
                        </span>
                      </div>
                      <div
                        className="truncate text-slate-900"
                        title={selected.sp_app_id}
                      >
                        <span className="text-muted-foreground">sp</span>{" "}
                        {selected.sp_app_id}
                      </div>
                    </div>
                    <Badge
                      variant="outline"
                      className="text-[11px] border-emerald-200 text-emerald-700 bg-emerald-50"
                    >
                      <ShieldCheck className="h-3 w-3 mr-1" />
                      token ready
                    </Badge>
                  </div>
                )}
              </div>
              <div className="space-y-3">
                <label className="text-xs uppercase tracking-wide text-muted-foreground font-semibold">
                  Question
                </label>
                <Textarea
                  rows={3}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  className="font-mono text-sm"
                />
                <div className="flex items-center gap-2 flex-wrap">
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold flex items-center gap-1.5">
                    <Lightbulb className="h-3 w-3" />
                    try
                  </div>
                  {SAMPLE_QUESTIONS.map((sq, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setQ(sq)}
                      disabled={busy}
                      className="text-[11px] px-2.5 py-1 rounded-full border bg-white hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {sq.length > 45 ? sq.slice(0, 42) + "…" : sq}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button
                    onClick={() => ask.mutate()}
                    disabled={!pick || !q.trim() || busy}
                    className="bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-700 hover:to-violet-700"
                  >
                    {ask.isPending ? (
                      <>
                        <Clock className="h-4 w-4 mr-2 animate-spin" />
                        Calling Genie…
                      </>
                    ) : (
                      <>
                        <Sparkles className="h-4 w-4 mr-2" />
                        Ask Genie
                      </>
                    )}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => sweepM.mutate()}
                    disabled={!q.trim() || busy}
                  >
                    {sweepM.isPending ? (
                      <>
                        <Clock className="h-4 w-4 mr-2 animate-spin" />
                        Running sweep…
                      </>
                    ) : (
                      <>
                        <Zap className="h-4 w-4 mr-2" />
                        Isolation sweep (all tenants)
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {ask.isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Genie call failed</AlertTitle>
          <AlertDescription>{(ask.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {ask.isPending && !answer && <AnswerSkeleton />}

      {answer && <AnswerCard a={answer} />}

      {sweepM.isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Sweep failed</AlertTitle>
          <AlertDescription>{(sweepM.error as Error).message}</AlertDescription>
        </Alert>
      )}

      {sweepM.isPending && <SweepSkeleton count={active.length || 3} />}

      {sweep && sweep.length > 0 && (
        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5 text-amber-500" />
              Isolation sweep
            </CardTitle>
            <CardDescription>
              Same question, every active tenant, in parallel. Genie usually
              generates identical SQL — the divergent numbers are from UC row
              filters, not the model.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {sweep.map((r) => (
                <SweepCard key={r.tenant_id} r={r} />
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function AnswerCard({ a }: { a: AskResponse }) {
  const firstRow = a.rows[0];
  const primaryMetric =
    firstRow && firstRow.length > 0 ? String(firstRow[0]) : null;
  return (
    <Card className="shadow-sm overflow-hidden">
      <div className="h-1 bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500" />
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-indigo-600" />
            {a.tenant_name}
          </CardTitle>
          <CardDescription className="font-mono text-xs truncate">
            <Plane className="h-3 w-3 inline mr-1 -mt-0.5" />
            {a.question}
          </CardDescription>
        </div>
        <div className="flex gap-2 flex-wrap justify-end shrink-0">
          <Badge
            variant="outline"
            className="font-mono text-[11px] border-emerald-200 text-emerald-700 bg-emerald-50"
          >
            {a.status}
          </Badge>
          <Badge variant="secondary" className="font-mono text-[11px]">
            <Clock className="h-3 w-3 mr-1" />
            {a.latency_ms} ms
          </Badge>
          <Badge variant="secondary" className="font-mono text-[11px]">
            <Columns className="h-3 w-3 mr-1" />
            {a.rows.length} rows
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {a.answer_text && (
          <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-4 text-sm leading-relaxed">
            {a.answer_text}
          </div>
        )}
        {a.sql && (
          <details className="rounded-md border bg-slate-50 p-3">
            <summary className="cursor-pointer text-xs font-medium flex items-center gap-1.5 select-none">
              <Code2 className="h-3.5 w-3.5" />
              Genie-generated SQL
            </summary>
            <pre className="mt-2 text-xs font-mono whitespace-pre-wrap overflow-x-auto text-slate-800">
              {a.sql}
            </pre>
          </details>
        )}
        {a.rows.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                {(a.columns.length
                  ? a.columns
                  : a.rows[0].map((_, i) => `c${i}`)
                ).map((c) => (
                  <TableHead key={c}>{c}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {a.rows.slice(0, 25).map((r, i) => (
                <TableRow key={i}>
                  {r.map((v, j) => (
                    <TableCell key={j} className="font-mono text-xs">
                      {v as any}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function SweepCard({ r }: { r: AskResponse }) {
  // Try to surface a headline number from the first row
  const first = r.rows[0] ?? [];
  const headline =
    first[0] !== undefined && first[0] !== null ? String(first[0]) : null;
  return (
    <Card className="shadow-sm hover:shadow-md transition-shadow border-slate-200">
      <div className="h-1 bg-gradient-to-r from-indigo-400 to-violet-400" />
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Bot className="h-4 w-4 text-indigo-600" />
            {r.tenant_name}
          </CardTitle>
          <Badge variant="outline" className="text-[10px] font-mono">
            {r.latency_ms} ms
          </Badge>
        </div>
        <CardDescription className="text-[11px] font-mono truncate">
          {r.sp_app_id.slice(0, 12)}…
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {headline && (
          <div className="text-2xl font-bold text-indigo-700 tracking-tight">
            {formatHeadline(headline)}
          </div>
        )}
        {r.answer_text && (
          <p className="text-xs leading-snug text-muted-foreground line-clamp-3">
            {r.answer_text}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function formatHeadline(raw: string): string {
  // If it's a number, format with commas
  const n = Number(raw);
  if (!Number.isNaN(n) && raw.trim() !== "") {
    if (Number.isInteger(n) && n < 100000) return n.toLocaleString();
    return n.toLocaleString(undefined, {
      maximumFractionDigits: 0,
    });
  }
  return raw;
}

function AnswerSkeleton() {
  return (
    <Card className="shadow-sm">
      <div className="h-1 bg-gradient-to-r from-indigo-200 via-violet-200 to-fuchsia-200 animate-pulse" />
      <CardContent className="py-6 space-y-3">
        <div className="h-4 w-1/3 bg-slate-100 rounded animate-pulse" />
        <div className="h-20 bg-slate-100 rounded-lg animate-pulse" />
      </CardContent>
    </Card>
  );
}

function SweepSkeleton({ count }: { count: number }) {
  return (
    <Card className="shadow-sm">
      <CardContent className="py-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: count }).map((_, i) => (
            <div
              key={i}
              className="h-32 rounded-lg border bg-slate-50 animate-pulse"
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
