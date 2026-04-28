import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  UserPlus,
  RotateCw,
  Trash2,
  KeyRound,
  AlertCircle,
  CheckCircle2,
  Clock,
  History,
} from "lucide-react";
import { api, type Tenant, type AuditRow } from "@/lib/api";

function statusBadge(status: string) {
  if (status === "active")
    return (
      <Badge className="bg-emerald-100 text-emerald-800 hover:bg-emerald-100 border-0">
        <CheckCircle2 className="h-3 w-3 mr-1" />
        active
      </Badge>
    );
  if (status === "deactivated")
    return (
      <Badge variant="secondary" className="bg-slate-200 text-slate-600">
        deactivated
      </Badge>
    );
  return <Badge variant="outline">{status}</Badge>;
}

function formatTs(iso: string | null | undefined) {
  if (!iso) return "—";
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

export function AdminPage() {
  const qc = useQueryClient();
  const tenants = useQuery({ queryKey: ["tenants"], queryFn: api.tenants });
  const audit = useQuery({
    queryKey: ["audit"],
    queryFn: () => api.audit(20),
    refetchInterval: 8000,
  });

  const [open, setOpen] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [lastOnboard, setLastOnboard] = useState<{
    client_id: string;
    client_secret: string;
  } | null>(null);
  const [lastRotate, setLastRotate] = useState<{
    tenant_id: string;
    new_client_secret: string;
  } | null>(null);

  const onboard = useMutation({
    mutationFn: () => api.onboard(newId, newName),
    onSuccess: (d) => {
      setLastOnboard({ client_id: d.client_id, client_secret: d.client_secret });
      setNewId("");
      setNewName("");
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
  const rotate = useMutation({
    mutationFn: (tid: string) => api.rotate(tid),
    onSuccess: (d) => {
      setLastRotate(d);
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });
  const deactivate = useMutation({
    mutationFn: (tid: string) => api.deactivate(tid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tenants"] });
      qc.invalidateQueries({ queryKey: ["audit"] });
    },
  });

  const data = tenants.data ?? [];
  const active = data.filter((t) => t.status === "active").length;
  const deact = data.filter((t) => t.status === "deactivated").length;

  return (
    <div className="space-y-6">
      {/* Stat header */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Client organizations"
          value={data.length}
          icon={UserPlus}
        />
        <StatCard
          label="Active"
          value={active}
          icon={CheckCircle2}
          tint="text-emerald-600"
        />
        <StatCard
          label="Deactivated"
          value={deact}
          icon={Trash2}
          tint="text-rose-600"
        />
      </div>

      {lastOnboard && (
        <Alert className="border-emerald-200 bg-emerald-50">
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          <AlertTitle className="text-emerald-900">Tenant onboarded</AlertTitle>
          <AlertDescription className="font-mono text-xs break-all text-emerald-800">
            client_id={lastOnboard.client_id}
            <br />
            client_secret={lastOnboard.client_secret}
            <br />
            <span className="text-emerald-700/60">
              Stored in .demo-secrets.env. The Client tab can now query Genie as
              this tenant.
            </span>
          </AlertDescription>
        </Alert>
      )}
      {lastRotate && (
        <Alert className="border-indigo-200 bg-indigo-50">
          <KeyRound className="h-4 w-4 text-indigo-600" />
          <AlertTitle className="text-indigo-900">
            Secret rotated for {lastRotate.tenant_id}
          </AlertTitle>
          <AlertDescription className="font-mono text-xs break-all text-indigo-800">
            new_client_secret={lastRotate.new_client_secret}
            <br />
            <span className="text-indigo-700/60">
              New secret active; old secrets revoked after new one was stored.
            </span>
          </AlertDescription>
        </Alert>
      )}

      {/* Tenants table */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>Client organization Service Principals</CardTitle>
            <CardDescription>
              One Databricks SP per BCD / Advito client organization. Each
              SP's identity flows into{" "}
              <code className="text-[11px] bg-slate-100 px-1 rounded">
                session_user()
              </code>{" "}
              for UC row-filter enforcement.
            </CardDescription>
          </div>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <UserPlus className="h-4 w-4 mr-2" />
                Onboard tenant
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Onboard a new client organization</DialogTitle>
                <DialogDescription>
                  Creates a workspace Service Principal, mints an OAuth secret,
                  stores it in the{" "}
                  <code className="text-[11px] bg-slate-100 px-1 rounded">
                    mt-genie-demo
                  </code>{" "}
                  secret scope, grants SELECT/USE on the demo catalog, grants
                  CAN_RUN on the Genie Space, and inserts the mapping row.
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-4 py-2">
                <div>
                  <label className="text-sm font-medium">
                    tenant_id (slug)
                  </label>
                  <Input
                    value={newId}
                    onChange={(e) => setNewId(e.target.value)}
                    placeholder="hersheys"
                    className="mt-1"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Display name</label>
                  <Input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                    placeholder="Hershey's"
                    className="mt-1"
                  />
                </div>
                {onboard.isError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      {(onboard.error as Error).message}
                    </AlertDescription>
                  </Alert>
                )}
              </div>
              <DialogFooter>
                <Button
                  onClick={() => onboard.mutate()}
                  disabled={!newId.trim() || !newName.trim() || onboard.isPending}
                >
                  {onboard.isPending ? (
                    <>
                      <Clock className="h-4 w-4 mr-2 animate-spin" />
                      Onboarding…
                    </>
                  ) : (
                    <>
                      <UserPlus className="h-4 w-4 mr-2" />
                      Onboard
                    </>
                  )}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent>
          {tenants.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading tenants…</p>
          ) : tenants.isError ? (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                {(tenants.error as Error).message}
              </AlertDescription>
            </Alert>
          ) : data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No tenants yet. Onboard your first one above.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tenant</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Service Principal</TableHead>
                  <TableHead>Secret</TableHead>
                  <TableHead>Updated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((t) => (
                  <TenantRow
                    key={t.tenant_id}
                    t={t}
                    onRotate={() => rotate.mutate(t.tenant_id)}
                    onDeactivate={() => {
                      if (
                        window.confirm(
                          `Deactivate ${t.tenant_name}? The SP will be disabled and the mapping row flipped off.`,
                        )
                      ) {
                        deactivate.mutate(t.tenant_id);
                      }
                    }}
                    rotating={rotate.isPending && rotate.variables === t.tenant_id}
                    deactivating={
                      deactivate.isPending && deactivate.variables === t.tenant_id
                    }
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Audit feed */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            Recent activity
          </CardTitle>
          <CardDescription>
            All admin operations write to <code>audit_log</code> with actor,
            tenant, action, and detail.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {audit.data && audit.data.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>When</TableHead>
                  <TableHead>Actor</TableHead>
                  <TableHead>Tenant</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Detail</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {audit.data.map((r: AuditRow, i: number) => (
                  <TableRow key={i}>
                    <TableCell className="whitespace-nowrap text-muted-foreground text-xs">
                      {formatTs(r.event_time)}
                    </TableCell>
                    <TableCell className="text-xs">{r.actor}</TableCell>
                    <TableCell className="text-xs font-medium">
                      {r.tenant_id}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{r.action}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={r.status === "ok" ? "default" : "destructive"}
                      >
                        {r.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground truncate max-w-[280px]">
                      {r.detail || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">No activity yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function TenantRow({
  t,
  onRotate,
  onDeactivate,
  rotating,
  deactivating,
}: {
  t: Tenant;
  onRotate: () => void;
  onDeactivate: () => void;
  rotating: boolean;
  deactivating: boolean;
}) {
  return (
    <TableRow>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-medium">{t.tenant_name}</span>
          <span className="text-xs text-muted-foreground font-mono">
            {t.tenant_id}
          </span>
        </div>
      </TableCell>
      <TableCell>{statusBadge(t.status)}</TableCell>
      <TableCell>
        <div className="flex flex-col">
          <span className="text-xs font-mono">{t.sp_display_name}</span>
          <span
            className="text-[11px] font-mono text-muted-foreground truncate max-w-[260px]"
            title={t.sp_app_id}
          >
            {t.sp_app_id}
          </span>
        </div>
      </TableCell>
      <TableCell>
        {t.has_local_secret ? (
          <Badge
            variant="outline"
            className="border-emerald-200 text-emerald-700 bg-emerald-50"
          >
            stored
          </Badge>
        ) : (
          <Badge
            variant="outline"
            className="border-amber-200 text-amber-700 bg-amber-50"
          >
            missing
          </Badge>
        )}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
        {formatTs(t.updated_at)}
      </TableCell>
      <TableCell className="text-right">
        <div className="flex gap-1 justify-end">
          <Button
            size="sm"
            variant="outline"
            onClick={onRotate}
            disabled={rotating || t.status === "deactivated"}
          >
            {rotating ? (
              <RotateCw className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCw className="h-3.5 w-3.5" />
            )}
            <span className="ml-1.5 hidden sm:inline">Rotate</span>
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="border-rose-200 text-rose-700 hover:bg-rose-50 hover:text-rose-700"
            onClick={onDeactivate}
            disabled={deactivating || t.status === "deactivated"}
          >
            {deactivating ? (
              <Clock className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            <span className="ml-1.5 hidden sm:inline">Deactivate</span>
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

function StatCard({
  label,
  value,
  icon: Icon,
  tint,
}: {
  label: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  tint?: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6 flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="text-3xl font-bold mt-1">{value}</p>
        </div>
        <Icon className={`h-8 w-8 ${tint ?? "text-muted-foreground/40"}`} />
      </CardContent>
    </Card>
  );
}
