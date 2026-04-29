const BASE = "/api";

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
}

export interface AuditRow {
  event_time: string | null;
  actor: string | null;
  tenant_id: string | null;
  action: string | null;
  sp_app_id: string | null;
  status: string | null;
  detail: string | null;
}

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

export const api = {
  workspace: () => http<WorkspaceInfo>("/workspace/info"),
  tenants: () => http<Tenant[]>("/tenants"),
  onboard: (tenant_id: string, tenant_name: string) =>
    http<{ tenant: Tenant; client_id: string; client_secret: string }>(
      "/tenants/onboard",
      { method: "POST", body: JSON.stringify({ tenant_id, tenant_name }) },
    ),
  rotate: (tenant_id: string) =>
    http<{ tenant_id: string; new_client_secret: string }>(
      `/tenants/${encodeURIComponent(tenant_id)}/rotate`,
      { method: "POST" },
    ),
  deactivate: (tenant_id: string) =>
    http<{ ok: boolean }>(
      `/tenants/${encodeURIComponent(tenant_id)}/deactivate`,
      { method: "POST" },
    ),
  audit: (limit = 50) => http<AuditRow[]>(`/tenants/audit?limit=${limit}`),
  mapping: () =>
    http<{ sp_app_id: string; tenant_id: string; active: boolean }[]>(
      "/tenants/mapping",
    ),
  ask: (tenant_id: string, question: string, conversation_id?: string | null) =>
    http<AskResponse>("/genie/ask", {
      method: "POST",
      body: JSON.stringify({ tenant_id, question, conversation_id }),
    }),
  sweep: (question: string) =>
    http<AskResponse[]>("/genie/sweep", {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
};
