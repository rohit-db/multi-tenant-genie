import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  Gauge,
  Route,
  Building2,
  AlertCircle,
  LayoutGrid,
  Sparkles,
} from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { api } from "@/lib/api";
import { useTenant } from "@/lib/tenant";
import { GenieDashboard } from "@/components/dashboards/GenieDashboard";
import { EmbeddedDashboard } from "@/components/dashboards/EmbeddedDashboard";
import { buildDashboards, type DashboardDef } from "@/lib/dashboards";
import { cn } from "@/lib/utils";

const DASH_ICONS = { gauge: Gauge, route: Route, building: Building2 } as const;

// Sentinel id for the native AI/BI embedded dashboard tab.
const NATIVE_ID = "__aibi__";

export function DashboardsPage() {
  const { selected, loading } = useTenant();
  const ws = useQuery({ queryKey: ["ws"], queryFn: api.workspace });
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const embedReady = !!ws.data?.embed_configured;

  const customDashboards: DashboardDef[] = useMemo(() => {
    if (!ws.data) return [];
    return buildDashboards(`${ws.data.catalog}.${ws.data.schema_name}`);
  }, [ws.data]);

  const initial = params.get("d");
  const [activeId, setActiveId] = useState<string | undefined>(
    initial ?? undefined,
  );

  // Default to the native AI/BI dashboard when available, else the first
  // curated SQL view.
  useEffect(() => {
    if (activeId) return;
    if (embedReady) setActiveId(NATIVE_ID);
    else if (customDashboards.length > 0) setActiveId(customDashboards[0].id);
  }, [activeId, embedReady, customDashboards]);

  const select = (id: string) => {
    setActiveId(id);
    params.set("d", id);
    setParams(params, { replace: true });
  };

  if (loading || ws.isLoading) {
    return <div className="h-[600px] animate-pulse rounded-xl bg-slate-100" />;
  }

  if (!selected) {
    return (
      <Alert>
        <AlertCircle className="h-4 w-4" />
        <AlertTitle>No active workspace</AlertTitle>
        <AlertDescription>
          Onboard a tenant in the operator console to view dashboards.
        </AlertDescription>
      </Alert>
    );
  }

  const isNative = activeId === NATIVE_ID;
  const activeCustom = customDashboards.find((d) => d.id === activeId);

  return (
    <div className="animate-fade-in space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-900">
            <LayoutGrid className="h-6 w-6 text-[var(--brand)]" />
            Dashboards
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Analytics for{" "}
            <span className="font-medium text-slate-700">
              {selected.tenant_name}
            </span>{" "}
            — every query runs as the tenant Service Principal, so Unity Catalog
            row filters scope the data automatically.
          </p>
        </div>
      </div>

      {/* View switcher: native AI/BI first, then curated SQL tiles */}
      <div className="flex flex-wrap gap-2">
        {embedReady && (
          <button
            type="button"
            onClick={() => select(NATIVE_ID)}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all",
              isNative
                ? "border-[var(--brand)] bg-[var(--brand-soft)] text-[var(--brand-strong)] shadow-sm"
                : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
            )}
          >
            <Sparkles className="h-4 w-4" />
            AI/BI Dashboard
          </button>
        )}
        {customDashboards.map((d) => {
          const Icon = DASH_ICONS[d.icon];
          const isActive = d.id === activeId;
          return (
            <button
              key={d.id}
              type="button"
              onClick={() => select(d.id)}
              className={cn(
                "flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm font-medium transition-all",
                isActive
                  ? "border-[var(--brand)] bg-[var(--brand-soft)] text-[var(--brand-strong)] shadow-sm"
                  : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-50",
              )}
            >
              <Icon className="h-4 w-4" />
              {d.title}
            </button>
          );
        })}
      </div>

      {isNative ? (
        <EmbeddedDashboard tenantId={selected.tenant_id} />
      ) : (
        activeCustom && (
          <GenieDashboard
            def={activeCustom}
            tenantId={selected.tenant_id}
            tenantName={selected.tenant_name}
            onAskFollowUp={() => navigate("/ask")}
          />
        )
      )}
    </div>
  );
}
