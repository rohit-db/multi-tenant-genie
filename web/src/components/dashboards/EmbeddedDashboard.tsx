import { useEffect, useRef, useState } from "react";
import { DatabricksDashboard } from "@databricks/aibi-client";
import { AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

type Status = "loading" | "ready" | "error" | "unconfigured";

/**
 * Renders a native Databricks AI/BI (Lakeview) dashboard, embedded for an
 * external user. The scoped token is minted server-side as the *tenant's*
 * Service Principal, so the dashboard's warehouse queries run as that SP and
 * the Unity Catalog row filter trims the data to the tenant — the same
 * isolation the Genie ask-path uses, enforced one layer down in the warehouse.
 */
export function EmbeddedDashboard({
  tenantId,
  height = 760,
}: {
  tenantId: string;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dashRef = useRef<DatabricksDashboard | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setError("");

    // Tear down any previous instance (tenant switch / remount).
    if (dashRef.current) {
      try {
        dashRef.current.destroy();
      } catch {
        /* no-op */
      }
      dashRef.current = null;
    }

    api
      .embedConfig(tenantId)
      .then((cfg) => {
        if (cancelled || !containerRef.current) return;
        const dashboard = new DatabricksDashboard({
          instanceUrl: cfg.instance_url,
          workspaceId: cfg.workspace_id,
          dashboardId: cfg.dashboard_id,
          token: cfg.embed_token,
          container: containerRef.current,
          // SDK refreshes ~5 min before the 1h token expires.
          getNewToken: async () => (await api.embedConfig(tenantId)).embed_token,
          colorScheme: "light",
          config: { version: 1, hideDatabricksLogo: true },
        });
        dashboard.initialize();
        dashRef.current = dashboard;
        setStatus("ready");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        // 503 = backend has no dashboard/workspace configured yet.
        setStatus(msg.startsWith("503") ? "unconfigured" : "error");
        setError(msg);
      });

    return () => {
      cancelled = true;
      if (dashRef.current) {
        try {
          dashRef.current.destroy();
        } catch {
          /* no-op */
        }
        dashRef.current = null;
      }
    };
  }, [tenantId]);

  if (status === "unconfigured") {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
        <div className="mb-1 flex items-center gap-2 font-semibold">
          <AlertCircle className="h-4 w-4" />
          Embedded dashboard not configured yet
        </div>
        <p className="text-amber-800">
          Publish an AI/BI dashboard with{" "}
          <code className="rounded bg-amber-100 px-1">embed_credentials=false</code>{" "}
          and set <code className="rounded bg-amber-100 px-1">MT_GENIE_DASHBOARD_ID</code>.
          Then run <span className="font-medium">Backfill grants</span> in the
          operator console so each tenant SP gets <code>CAN RUN</code>.
        </p>
      </div>
    );
  }

  return (
    <div className="relative">
      {status === "loading" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-white/70">
          <Loader2 className="h-6 w-6 animate-spin text-[var(--brand)]" />
        </div>
      )}
      {status === "error" && (
        <div className="mb-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          Could not load the embedded dashboard: {error}
        </div>
      )}
      <div
        ref={containerRef}
        style={{ height }}
        className="w-full overflow-hidden rounded-xl border border-slate-200 bg-white"
      />
    </div>
  );
}
