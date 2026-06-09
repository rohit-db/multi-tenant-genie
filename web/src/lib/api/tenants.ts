// Tenant list + SP lifecycle (operator surface), plus the bulk-onboard job
// poll and the grant backfill.
import { http } from "./http";
import type {
  AuditRow,
  BulkOnboardInput,
  BulkOnboardResponse,
  JobStatus,
  OnboardResponse,
  RotateResponse,
  Tenant,
} from "./types";

export const tenantsApi = {
  tenants: () => http<Tenant[]>("/tenants"),
  onboard: (tenant_id: string, tenant_name: string) =>
    http<OnboardResponse>("/tenants/onboard", {
      method: "POST",
      body: JSON.stringify({ tenant_id, tenant_name }),
    }),
  bulkOnboard: (tenants: BulkOnboardInput[]) =>
    http<BulkOnboardResponse>("/tenants/bulk", {
      method: "POST",
      body: JSON.stringify({ tenants }),
    }),
  rotate: (tenant_id: string) =>
    http<RotateResponse>(
      `/tenants/${encodeURIComponent(tenant_id)}/rotate`,
      { method: "POST" },
    ),
  deactivate: (tenant_id: string) =>
    http<{ ok: boolean }>(
      `/tenants/${encodeURIComponent(tenant_id)}/deactivate`,
      { method: "POST" },
    ),
  reactivate: (tenant_id: string) =>
    http<RotateResponse>(
      `/tenants/${encodeURIComponent(tenant_id)}/reactivate`,
      { method: "POST" },
    ),
  delete: (tenant_id: string) =>
    http<{ ok: boolean }>(
      `/tenants/${encodeURIComponent(tenant_id)}`,
      { method: "DELETE" },
    ),
  history: (tenant_id: string, limit = 50) =>
    http<AuditRow[]>(
      `/tenants/${encodeURIComponent(tenant_id)}/history?limit=${limit}`,
    ),

  // Bulk-onboard job status poll.
  job: (job_id: string) => http<JobStatus>(`/jobs/${encodeURIComponent(job_id)}`),

  // Re-apply data + Genie + dashboard (CAN RUN) grants to all active tenants.
  backfillGrants: () =>
    http<Record<string, string>>("/tenants/grants/backfill", { method: "POST" }),
};
