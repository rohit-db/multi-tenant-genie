import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Upload, AlertCircle, CheckCircle2 } from "lucide-react";
import { api, type BulkOnboardInput, type JobStatus } from "@/lib/api";

interface BulkOnboardDialogProps {
  trigger: React.ReactNode;
}

export function BulkOnboardDialog({ trigger }: BulkOnboardDialogProps) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [parsed, setParsed] = useState<BulkOnboardInput[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);

  const start = useMutation({
    mutationFn: () => api.bulkOnboard(parsed),
    onSuccess: (r) => setJobId(r.job_id),
  });

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data as JobStatus | undefined;
      return data && data.state === "completed" ? false : 500;
    },
  });

  // Re-parse on input change
  useEffect(() => {
    if (!input.trim()) {
      setParsed([]);
      setParseError(null);
      return;
    }
    try {
      setParsed(parseInput(input));
      setParseError(null);
    } catch (e) {
      setParseError((e as Error).message);
      setParsed([]);
    }
  }, [input]);

  // Refresh tenants list once the job completes
  useEffect(() => {
    if (job.data && job.data.state === "completed") {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    }
  }, [job.data, qc]);

  function handleClose(next: boolean) {
    if (!next) {
      setInput("");
      setParsed([]);
      setParseError(null);
      setJobId(null);
    }
    setOpen(next);
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Bulk onboard tenants</DialogTitle>
          <DialogDescription>
            Paste JSON (
            <code className="text-[11px] bg-slate-100 px-1 rounded">
              [{`{"tenant_id":"a","tenant_name":"A"}`}]
            </code>
            ) or CSV (
            <code className="text-[11px] bg-slate-100 px-1 rounded">
              tenant_id,tenant_name
            </code>{" "}
            header required). Each row creates an SP, mints an OAuth secret,
            and registers the mapping.
          </DialogDescription>
        </DialogHeader>

        {!jobId && (
          <div className="space-y-3 py-1">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={'[\n  {"tenant_id": "acme", "tenant_name": "Acme"},\n  {"tenant_id": "globex", "tenant_name": "Globex"}\n]'}
              className="min-h-[180px] font-mono text-xs"
            />
            {parseError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{parseError}</AlertDescription>
              </Alert>
            )}
            {parsed.length > 0 && !parseError && (
              <div className="text-xs text-muted-foreground">
                Parsed {parsed.length} tenant{parsed.length === 1 ? "" : "s"}.
              </div>
            )}
          </div>
        )}

        {jobId && job.data && (
          <div className="space-y-3 py-1">
            <ProgressBar processed={job.data.processed} total={job.data.total} />
            <div className="text-xs text-muted-foreground">
              {job.data.state === "completed"
                ? `Completed: ${job.data.results.length} ok, ${job.data.errors.length} failed`
                : `Running: ${job.data.processed} / ${job.data.total}`}
            </div>
            {job.data.state === "completed" && (
              <ResultsList job={job.data} />
            )}
          </div>
        )}

        <DialogFooter>
          {!jobId ? (
            <Button
              onClick={() => start.mutate()}
              disabled={parsed.length === 0 || !!parseError || start.isPending}
            >
              <Upload className="h-4 w-4 mr-2" />
              {start.isPending ? "Starting…" : `Run on ${parsed.length}`}
            </Button>
          ) : (
            <Button
              variant="outline"
              onClick={() => handleClose(false)}
              disabled={!job.data || job.data.state !== "completed"}
            >
              {job.data?.state === "completed" ? "Close" : "Running…"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProgressBar({ processed, total }: { processed: number; total: number }) {
  const pct = total === 0 ? 0 : Math.min(100, Math.round((processed / total) * 100));
  return (
    <div className="w-full bg-slate-200 rounded h-2 overflow-hidden">
      <div
        className="bg-indigo-500 h-full transition-[width] duration-100"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function ResultsList({ job }: { job: JobStatus }) {
  return (
    <div className="space-y-1 max-h-[200px] overflow-y-auto rounded border bg-white p-2">
      {job.errors.map((e) => (
        <div key={e.tenant_id} className="text-xs flex items-start gap-2">
          <AlertCircle className="h-3.5 w-3.5 text-rose-600 shrink-0 mt-0.5" />
          <span className="font-mono">{e.tenant_id}</span>
          <span className="text-rose-700 truncate">{e.error}</span>
        </div>
      ))}
      {job.results.map((r) => (
        <div key={r.tenant_id} className="text-xs flex items-center gap-2">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
          <span className="font-mono">{r.tenant_id}</span>
          <Badge variant="outline" className="text-[10px]">
            {r.sp_app_id.slice(0, 12)}…
          </Badge>
        </div>
      ))}
    </div>
  );
}

function parseInput(raw: string): BulkOnboardInput[] {
  const trimmed = raw.trim();
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    return parseJson(trimmed);
  }
  return parseCsv(trimmed);
}

function parseJson(raw: string): BulkOnboardInput[] {
  let v: unknown;
  try {
    v = JSON.parse(raw);
  } catch (e) {
    throw new Error(`Invalid JSON: ${(e as Error).message}`);
  }
  const arr = Array.isArray(v) ? v : [v];
  const out: BulkOnboardInput[] = [];
  for (const r of arr) {
    if (!r || typeof r !== "object") {
      throw new Error("Each entry must be an object with tenant_id and tenant_name");
    }
    const o = r as Record<string, unknown>;
    const tenant_id = String(o.tenant_id ?? "").trim();
    const tenant_name = String(o.tenant_name ?? "").trim();
    if (!tenant_id || !tenant_name) {
      throw new Error("Every entry needs tenant_id and tenant_name");
    }
    out.push({ tenant_id, tenant_name });
  }
  return out;
}

function parseCsv(raw: string): BulkOnboardInput[] {
  const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length < 2) {
    throw new Error("CSV needs a header row and at least one data row");
  }
  const header = lines[0].split(",").map((c) => c.trim().toLowerCase());
  const idIdx = header.indexOf("tenant_id");
  const nameIdx = header.indexOf("tenant_name");
  if (idIdx === -1 || nameIdx === -1) {
    throw new Error("CSV header must include tenant_id and tenant_name");
  }
  const out: BulkOnboardInput[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split(",").map((c) => c.trim());
    const tenant_id = cols[idIdx];
    const tenant_name = cols[nameIdx];
    if (!tenant_id || !tenant_name) {
      throw new Error(`Row ${i + 1}: tenant_id and tenant_name required`);
    }
    out.push({ tenant_id, tenant_name });
  }
  return out;
}
