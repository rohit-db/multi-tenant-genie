import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Shield, AlertCircle, CheckCircle2, XCircle } from "lucide-react";
import { api, type VerifyResultRow } from "@/lib/api";

interface VerifyIsolationModalProps {
  trigger: React.ReactNode;
}

export function VerifyIsolationModal({ trigger }: VerifyIsolationModalProps) {
  const [open, setOpen] = useState(false);
  const verify = useMutation({
    mutationFn: () => api.verify(),
  });

  function handleOpenChange(next: boolean) {
    if (!next) verify.reset();
    setOpen(next);
  }

  const results = verify.data ?? null;
  const passing = results?.filter((r) => r.passed).length ?? 0;
  const failing = (results?.length ?? 0) - passing;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Verify isolation</DialogTitle>
          <DialogDescription>
            Each active tenant's Service Principal queries{" "}
            <code className="text-[11px] bg-slate-100 px-1 rounded">
              SELECT DISTINCT tenant_id FROM bookings
            </code>
            . If the only visible tenant_id is its own, the row filter is
            enforcing correctly.
          </DialogDescription>
        </DialogHeader>

        {!results && !verify.isError && (
          <p className="text-sm text-muted-foreground">
            {verify.isPending
              ? "Running queries against your warehouse…"
              : "Click Run to start. Each tenant exchanges its OAuth secret for a token, then queries the bookings table."}
          </p>
        )}

        {verify.isError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {(verify.error as Error).message}
            </AlertDescription>
          </Alert>
        )}

        {results && (
          <div className="space-y-3">
            <div className="flex items-center gap-3 text-sm">
              <Badge className="bg-emerald-100 text-emerald-800 border-0">
                <CheckCircle2 className="h-3 w-3 mr-1" />
                {passing} passing
              </Badge>
              {failing > 0 && (
                <Badge variant="destructive">
                  <XCircle className="h-3 w-3 mr-1" />
                  {failing} failing
                </Badge>
              )}
            </div>
            <div className="rounded border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tenant</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Visible tenant_ids</TableHead>
                    <TableHead>Detail</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.map((r) => (
                    <ResultRow key={r.tenant_id} r={r} />
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            onClick={() => verify.mutate()}
            disabled={verify.isPending}
          >
            <Shield className="h-4 w-4 mr-2" />
            {verify.isPending ? "Running…" : results ? "Re-run" : "Run"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResultRow({ r }: { r: VerifyResultRow }) {
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col">
          <span className="text-sm font-medium">{r.tenant_name}</span>
          <span className="text-xs font-mono text-muted-foreground">
            {r.tenant_id}
          </span>
        </div>
      </TableCell>
      <TableCell>
        {r.passed ? (
          <Badge className="bg-emerald-100 text-emerald-800 border-0">
            <CheckCircle2 className="h-3 w-3 mr-1" />
            pass
          </Badge>
        ) : (
          <Badge variant="destructive">
            <XCircle className="h-3 w-3 mr-1" />
            fail
          </Badge>
        )}
      </TableCell>
      <TableCell className="text-xs font-mono">
        {r.distinct_tenant_ids.length === 0
          ? "—"
          : r.distinct_tenant_ids.join(", ")}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground max-w-[280px] truncate">
        {r.error ? r.error : `expected ${r.tenant_id}, got ${r.distinct_tenant_ids.join(", ") || "(empty)"}`}
      </TableCell>
    </TableRow>
  );
}
