import { useQuery } from "@tanstack/react-query";
import { Gauge, Route, Building2, Lock, MessageSquarePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { AnswerViz } from "@/components/ask/AnswerViz";
import { api } from "@/lib/api";
import type { DashboardDef, DashboardTile } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const ICONS = {
  gauge: Gauge,
  route: Route,
  building: Building2,
} as const;

interface GenieDashboardProps {
  def: DashboardDef;
  tenantId: string;
  tenantName: string;
  onAskFollowUp?: () => void;
}

/**
 * Renders a curated dashboard: each tile runs deterministic SQL as the tenant
 * SP and auto-visualizes. Mimics opening a saved dashboard inside a Genie
 * space — but every number is row-filtered to this tenant.
 */
export function GenieDashboard({
  def,
  tenantId,
  tenantName,
  onAskFollowUp,
}: GenieDashboardProps) {
  const Icon = ICONS[def.icon];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-indigo-500 to-violet-600 shadow-sm">
            <Icon className="h-4 w-4 text-white" />
          </span>
          <div className="min-w-0">
            <h2 className="text-base font-semibold tracking-tight text-slate-900">
              {def.title}
            </h2>
            <p className="text-sm text-slate-500">{def.description}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="gap-1 border-emerald-200 bg-emerald-50 text-[11px] text-emerald-700"
          >
            <Lock className="h-3 w-3" />
            {tenantName} only
          </Badge>
          {onAskFollowUp && (
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              onClick={onAskFollowUp}
            >
              <MessageSquarePlus className="h-3.5 w-3.5" />
              Ask a follow-up
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {def.tiles.map((tile) => (
          <Tile
            key={tile.title}
            tile={tile}
            tenantId={tenantId}
            className={tile.wide ? "lg:col-span-2" : ""}
          />
        ))}
      </div>
    </div>
  );
}

function Tile({
  tile,
  tenantId,
  className,
}: {
  tile: DashboardTile;
  tenantId: string;
  className?: string;
}) {
  const q = useQuery({
    queryKey: ["dash-sql", tenantId, tile.sql],
    queryFn: () => api.runSql(tenantId, tile.sql),
    staleTime: 60_000,
    retry: false,
  });

  return (
    <div
      className={cn(
        "rounded-xl border border-slate-200 bg-white p-4 shadow-sm",
        className,
      )}
    >
      <div className="mb-3">
        <div className="text-sm font-semibold text-slate-800">{tile.title}</div>
        {tile.description && (
          <div className="text-xs text-slate-500">{tile.description}</div>
        )}
      </div>

      {q.isLoading ? (
        <div className="h-44 animate-pulse rounded-lg bg-slate-100" />
      ) : q.isError ? (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {(q.error as Error).message}
        </div>
      ) : q.data && q.data.rows.length > 0 ? (
        <AnswerViz columns={q.data.columns} rows={q.data.rows} />
      ) : (
        <div className="flex h-32 items-center justify-center text-xs text-slate-400">
          No data for this tenant
        </div>
      )}
    </div>
  );
}
