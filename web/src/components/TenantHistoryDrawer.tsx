import { useQuery } from "@tanstack/react-query";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

interface TenantHistoryDrawerProps {
  tenantId: string | null;
  tenantName: string | null;
  onOpenChange: (open: boolean) => void;
}

export function TenantHistoryDrawer({
  tenantId,
  tenantName,
  onOpenChange,
}: TenantHistoryDrawerProps) {
  const open = tenantId !== null;
  const history = useQuery({
    queryKey: ["history", tenantId],
    queryFn: () => api.history(tenantId!, 50),
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Activity for {tenantName ?? tenantId}</DialogTitle>
          <DialogDescription>
            Last 50 events from the audit log for this tenant.
          </DialogDescription>
        </DialogHeader>

        {history.isLoading && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {history.isError && (
          <p className="text-sm text-rose-700">
            {(history.error as Error).message}
          </p>
        )}
        {history.data && history.data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No activity yet for this tenant.
          </p>
        )}
        {history.data && history.data.length > 0 && (
          <div className="max-h-[440px] overflow-y-auto rounded border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[140px]">When</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Latency</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {history.data.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-xs whitespace-nowrap text-muted-foreground">
                      {formatTs(r.created_at)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.action}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          r.status === "completed" || r.status === "ok"
                            ? "default"
                            : "destructive"
                        }
                      >
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs whitespace-nowrap">
                      {r.latency_ms != null ? `${r.latency_ms} ms` : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground truncate max-w-[300px]">
                      {r.question ?? r.detail ?? "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}
