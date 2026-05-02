const BASE = "/api";

// ============================================================================
// Types
// ============================================================================

export interface Tenant {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  sp_display_name: string;
  status: "active" | "rotating" | "deactivated" | string;
  created_at: string;
  updated_at: string;
}

export interface WorkspaceInfo {
  host: string;
  catalog: string;
  schema_name: string;
  genie_space_id: string;
  warehouse_name: string;
  admin_group: string;
}

export interface InspectorStep {
  n: number;
  name: string;
  summary: string | null;
  code_snippet: string | null;
  payload_in: Record<string, unknown> | null;
  payload_out: Record<string, unknown> | null;
  duration_ms: number;
  error: string | null;
}

export interface InspectorPayload {
  request_id: string;
  steps: InspectorStep[];
}

export interface AskResponse {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  question: string;
  answer_text: string | null;
  sql: string | null;
  columns: string[];
  rows: (string | number | null)[][];
  latency_ms: number;
  conversation_id: string | null;
  message_id: string | null;
  status: string;
  inspector: InspectorPayload | null;
}

export interface AuditRow {
  id: number;
  tenant_id: string | null;
  actor: string | null;
  action: string;
  sp_app_id: string | null;
  question: string | null;
  status: string;
  latency_ms: number | null;
  detail: string | null;
  created_at: string;
}

export interface MappingRow {
  sp_app_id: string;
  tenant_id: string;
  active: boolean;
}

export interface OnboardResponse {
  tenant: Tenant;
  client_id: string;
  client_secret: string;
}

export interface RotateResponse {
  tenant_id: string;
  new_client_secret: string;
}

export interface BulkOnboardInput {
  tenant_id: string;
  tenant_name: string;
}

export interface BulkOnboardResponse {
  job_id: string;
}

export interface BulkOnboardJobError {
  tenant_id: string;
  error: string;
}

export interface BulkOnboardJobResult {
  tenant_id: string;
  tenant_name: string;
  sp_app_id: string;
  client_secret: string;
}

export interface JobStatus {
  job_id: string;
  state: "running" | "completed" | string;
  total: number;
  processed: number;
  errors: BulkOnboardJobError[];
  results: BulkOnboardJobResult[];
}

export interface VerifyResultRow {
  tenant_id: string;
  tenant_name: string;
  passed: boolean;
  distinct_tenant_ids: string[];
  visible_row_count: number | null;
  error: string | null;
}

// ============================================================================
// HTTP helper
// ============================================================================

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? `: ${text}` : ""}`);
  }
  return res.json();
}

// ============================================================================
// API surface
// ============================================================================

export const api = {
  // Workspace info
  workspace: () => http<WorkspaceInfo>("/workspace/info"),

  // Tenants — list + lifecycle
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

  // Jobs
  job: (job_id: string) => http<JobStatus>(`/jobs/${encodeURIComponent(job_id)}`),

  // Audit + mapping (moved out of /tenants in Phase 2)
  audit: (limit = 50) => http<AuditRow[]>(`/audit?limit=${limit}`),
  mapping: () => http<MappingRow[]>("/audit/mapping"),

  // Verify
  verify: () => http<VerifyResultRow[]>("/verify", { method: "POST" }),

  // Genie
  ask: (
    tenant_id: string,
    question: string,
    options?: { conversation_id?: string | null; inspect?: boolean },
  ) => {
    const url = options?.inspect ? "/genie/ask?inspect=true" : "/genie/ask";
    return http<AskResponse>(url, {
      method: "POST",
      body: JSON.stringify({
        tenant_id,
        question,
        conversation_id: options?.conversation_id ?? null,
      }),
    });
  },
  sweep: (question: string) =>
    http<AskResponse[]>("/genie/sweep", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),

  // Direct SQL — runs as the tenant SP via the warehouse, row filter still applies.
  // Used for deterministic dashboard widgets (no Genie roundtrip).
  runSql: (tenant_id: string, sql: string) =>
    http<{
      columns: string[];
      rows: (string | number | null)[][];
      latency_ms: number;
    }>("/genie/sql", {
      method: "POST",
      body: JSON.stringify({ tenant_id, sql }),
    }),

  // Custom agent — plan→execute→synthesize, every tool call goes through
  // the tenant SP so the row filter applies.
  agentInsights: (tenant_id: string, focus: string) =>
    http<{
      tenant_id: string;
      focus: string;
      model: string;
      reasoning: string | null;
      tool_calls: Array<{
        name: string;
        sql: string;
        columns?: string[];
        rows?: (string | number | null)[][];
        row_count?: number;
        latency_ms?: number;
        error?: string;
      }>;
      recommendation: string;
    }>("/agent/insights", {
      method: "POST",
      body: JSON.stringify({ tenant_id, focus }),
    }),
};
